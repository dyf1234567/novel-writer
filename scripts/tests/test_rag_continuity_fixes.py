"""RAG 连续性修复（P0 四项）专项测试。

修复对象：
1. 普通 LLM 写作路径未注入 RAG/约束上下文（additional_context 追加式注入）
2. Beat Sheet 路径 query[:200] 截断导致 RAG 上下文丢失
3. 索引构建不受门禁保护（失败章/占位章也会进索引）
4. 模板兜底正文无来源标记，可混过门禁并污染索引
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
EXECUTOR = SCRIPTS_DIR / "novel_flow_executor.py"
GATE_CHECK = SCRIPTS_DIR / "chapter_gate_check.py"
BEAT_GEN = SCRIPTS_DIR / "beat_sheet_generator.py"
RETRIEVER = SCRIPTS_DIR / "plot_rag_retriever.py"

_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _run(script, args):
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, env=_ENV,
    )
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        payload = None
    return proc.returncode, payload, proc


def _init_project(root: Path):
    code, payload, proc = _run(EXECUTOR, [
        "one-click", "--project-root", str(root),
        "--title", "雾港回声", "--genre", "悬疑", "--idea", "主角在旧港区发现失踪名单",
    ])
    assert payload and payload.get("ok"), f"one-click 失败: {proc.stdout} {proc.stderr}"


class TestAdditionalContextInjection(unittest.TestCase):
    """P0-1：普通 LLM 路径必须携带 RAG/约束上下文。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rag_fix_ctx_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_writer_appends_additional_context(self):
        """write_chapter 应把 config['additional_context'] 追加进最终 prompt。"""
        sys.path.insert(0, str(SCRIPTS_DIR))
        import novel_chapter_writer as ncw

        manuscript = self.tmpdir / "03_manuscript"
        manuscript.mkdir(parents=True, exist_ok=True)
        chapter = manuscript / "第1章-待写.md"
        chapter.write_text("# 第1章\n\n[待写]\n", encoding="utf-8")

        marker_text = "RAG片段：第0章主角曾在站台见过名单"
        result = ncw.write_chapter(
            self.tmpdir,
            chapter_file=chapter,
            config_overrides={"additional_context": marker_text},
            dry_run=True,
        )
        self.assertTrue(result.get("ok"))
        self.assertIn(
            marker_text, result.get("prompt", ""),
            "additional_context 未出现在最终 prompt 中",
        )

    def test_executor_passes_additional_context_to_write_chapter(self):
        """executor 的整章 LLM 调用前必须设置 config_overrides['additional_context']。"""
        import inspect
        sys.path.insert(0, str(SCRIPTS_DIR))
        import novel_flow_executor as nfe

        src = inspect.getsource(nfe)
        call_sig = "llm_result = write_chapter("
        idx = src.rfind(call_sig)  # 整章调用是最后一处（Beat 扩写调用在其之前）
        self.assertGreater(idx, 0, "未找到整章 write_chapter 调用")
        window = src[max(0, idx - 900): idx]
        self.assertIn(
            "additional_context", window,
            "整章 write_chapter 调用前未设置 additional_context",
        )


class TestBeatContextNotTruncated(unittest.TestCase):
    """P0-2：Beat 路径不得把 RAG 上下文截断在 200 字以内。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rag_fix_beat_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_beat_generate_and_expand_carry_retrieval_context(self):
        retrieval_text = "第3章：主角把A17坐标抄在笔记本上；第5章：李四曾独自去过临海港"
        code, payload, proc = _run(BEAT_GEN, [
            "generate", "--project-root", str(self.tmpdir), "--chapter", "6",
            "--chapter-goal", "主角发现李四可能背叛",
            "--retrieval-context", retrieval_text,
        ])
        self.assertEqual(code, 0, f"generate 失败: {proc.stderr}")
        self.assertIsNotNone(payload, f"generate 输出非 JSON: {proc.stdout}")
        self.assertTrue(payload.get("ok"))

        sheet_file = Path(payload["beat_sheet_file"])
        sheet = json.loads(sheet_file.read_text(encoding="utf-8"))
        self.assertEqual(
            sheet.get("retrieval_context"), retrieval_text,
            "beat sheet JSON 未保存 retrieval_context",
        )

        code2, payload2, proc2 = _run(BEAT_GEN, [
            "expand", "--project-root", str(self.tmpdir), "--chapter", "6", "--beat-id", "1",
        ])
        self.assertEqual(code2, 0, f"expand 失败: {proc2.stderr}")
        self.assertIsNotNone(payload2)
        self.assertIn(
            "A17坐标", payload2.get("expand_prompt", ""),
            "expand prompt 未携带检索上下文",
        )

    def test_no_200_char_truncation_in_beat_pipeline(self):
        """_generate_beat_draft 源码中不得再出现 query[:200] 截断。"""
        import inspect
        sys.path.insert(0, str(SCRIPTS_DIR))
        import novel_flow_executor as nfe

        src = inspect.getsource(nfe._generate_beat_draft)
        self.assertNotIn("query[:200]", src, "Beat 管线仍存在 query[:200] 截断")


class TestGatedIndexAndFallbackStatus(unittest.TestCase):
    """P0-3/P0-4：索引受门禁保护；模板兜底正文被显式标记并被门禁拦截。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rag_fix_gate_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gate_blocks_fallback_template_marker(self):
        """含 NOVEL_DRAFT_STATUS: fallback_template 标记的章节必须门禁失败。"""
        manuscript = self.tmpdir / "03_manuscript"
        manuscript.mkdir(parents=True, exist_ok=True)
        chapter = manuscript / "第2章-模板.md"
        chapter.write_text(
            "# 第2章 模板\n\n<!-- NOVEL_DRAFT_STATUS: fallback_template -->\n\n"
            + "主角走向站台，事情复杂。\n\n" * 30,
            encoding="utf-8",
        )
        code, payload, proc = _run(GATE_CHECK, [
            "--project-root", str(self.tmpdir), "--chapter-file", str(chapter),
        ])
        self.assertIsNotNone(payload, f"门禁输出非 JSON: {proc.stdout}")
        self.assertFalse(payload.get("passed"))
        self.assertTrue(
            any("generation_status" in f for f in payload.get("failures", [])),
            f"门禁 failures 中缺少 generation_status 硬失败: {payload.get('failures')}",
        )

    def test_gate_blocks_fallback_status_sidecar(self):
        """generation_status.json 标记为 fallback_template 且哈希匹配时门禁必须失败。"""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from common import file_sha1, slugify

        manuscript = self.tmpdir / "03_manuscript"
        manuscript.mkdir(parents=True, exist_ok=True)
        chapter = manuscript / "第3章-成稿.md"
        chapter.write_text("# 第3章 成稿\n\n" + "正常的正文段落。\n\n" * 30, encoding="utf-8")
        gate_dir = self.tmpdir / "04_editing" / "gate_artifacts" / slugify(chapter.stem)
        gate_dir.mkdir(parents=True, exist_ok=True)
        (gate_dir / "generation_status.json").write_text(
            json.dumps({
                "generation_status": "fallback_template",
                "publishable": False,
                "chapter_hash": file_sha1(chapter),
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        code, payload, proc = _run(GATE_CHECK, [
            "--project-root", str(self.tmpdir), "--chapter-file", str(chapter),
        ])
        self.assertIsNotNone(payload)
        self.assertTrue(
            any("generation_status" in f for f in payload.get("failures", [])),
            f"门禁 failures 中缺少 generation_status 硬失败: {payload.get('failures')}",
        )

    def test_index_skipped_when_gate_fails(self):
        """门禁未通过时不得重建索引（index_result.skipped=True）。"""
        _init_project(self.tmpdir)
        chapter = self.tmpdir / "03_manuscript" / "第2章-短章.md"
        chapter.write_text("# 第2章 短章\n\n这是一段极短正文。", encoding="utf-8")
        code, payload, proc = _run(EXECUTOR, [
            "continue-write", "--project-root", str(self.tmpdir),
            "--chapter-file", str(chapter),
            "--query", "主角推进剧情",
            "--no-auto-draft", "--no-auto-improve", "--no-auto-retry",
            "--min-paragraphs", "12", "--no-rollback-on-failure", "--force-run",
        ])
        self.assertIsNotNone(payload, f"输出非 JSON: {proc.stdout}")
        self.assertFalse(payload.get("gate_passed_final"))
        index_result = payload.get("index_result") or {}
        self.assertTrue(
            index_result.get("skipped"),
            f"门禁失败时索引仍被执行: {index_result}",
        )
        self.assertEqual(index_result.get("reason"), "gate_not_passed")


class TestRetrievalResilience(unittest.TestCase):
    """步骤5/6：检索三态与降级、缓存 TTL、角色签名、元数据稳定命名。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rag_resilience_"))
        (self.tmpdir / "00_memory" / "retrieval").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "03_manuscript").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "00_memory" / "character_tracker.md").write_text(
            "| 姓名 | 当前状态 |\n| --- | --- |\n| 张三 | 存活 |\n",
            encoding="utf-8",
        )
        (self.tmpdir / "03_manuscript" / "第1章-开篇.md").write_text(
            "# 第1章 开篇\n\n"
            + "张三走进临海港的旧站台，风里带着铁锈味。他翻开笔记本，"
              "把失踪名单上的名字又核对了一遍， numbering 无误。\n\n" * 8,
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cache_entry_expires_after_ttl(self):
        """超过 TTL（默认 1 小时）的查询缓存不得命中。"""
        sys.path.insert(0, str(SCRIPTS_DIR))
        import plot_rag_retriever as prr

        query_text = "张三在站台发现名单并与人发生冲突"
        index = prr.build_index(self.tmpdir)
        idx_sig = prr.index_signature(index)
        key = prr.make_cache_key(query_text, 4, 2, 220, f"{idx_sig}|cand=12")
        cache_file = self.tmpdir / "00_memory" / "retrieval" / "query_cache.json"
        stale_result = {
            "query": query_text, "query_entities": ["张三"],
            "retrieved": [], "relation_snippets": [], "retrieval_stats": {},
        }
        cache_file.write_text(
            json.dumps({"entries": {key: {
                "saved_at": "2000-01-01 00:00:00", "result": stale_result,
            }}}, ensure_ascii=False),
            encoding="utf-8",
        )
        code, payload, proc = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", query_text, "--auto-build",
        ])
        self.assertIsNotNone(payload, f"输出非 JSON: {proc.stdout} {proc.stderr}")
        self.assertTrue(payload.get("ok"))
        self.assertFalse(
            payload.get("cache_hit", False),
            "超过 TTL 的缓存不应命中（缓存时间 2000 年）",
        )

    def test_cache_invalidated_when_characters_change(self):
        """角色表变化（角色签名变化）后，查询缓存必须失效。"""
        query_text = "张三在站台发现名单并与人发生冲突"
        code1, payload1, _ = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", query_text, "--auto-build",
        ])
        self.assertTrue(payload1 and payload1.get("ok"))

        tracker = self.tmpdir / "00_memory" / "character_tracker.md"
        tracker.write_text(
            "| 姓名 | 当前状态 |\n| --- | --- |\n| 张三 | 存活 |\n| 王五 | 存活 |\n",
            encoding="utf-8",
        )
        code2, payload2, proc2 = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", query_text, "--auto-build",
        ])
        self.assertIsNotNone(payload2, f"输出非 JSON: {proc2.stdout} {proc2.stderr}")
        self.assertFalse(
            payload2.get("cache_hit", False),
            "角色表变化后缓存不应命中（角色签名应纳入缓存键）",
        )

    def test_chapter_meta_files_use_stable_ids(self):
        """章节 meta 文件应使用稳定 ID（chNNNN.meta.json）而非中文标题 slug。"""
        import re as _re
        sys.path.insert(0, str(SCRIPTS_DIR))
        import plot_rag_retriever as prr

        prr.build_index(self.tmpdir)
        meta_dir = self.tmpdir / "00_memory" / "retrieval" / "chapter_meta"
        names = sorted(p.name for p in meta_dir.glob("*.meta.json"))
        self.assertTrue(names, "应生成章节 meta 文件")
        self.assertTrue(
            all(_re.fullmatch(r"ch\d{4}\.meta\.json", n) for n in names),
            f"meta 文件应使用稳定 ID 命名（chNNNN.meta.json），实际: {names}",
        )

    def test_continue_write_reports_retrieval_status(self):
        """continue-write 结果必须包含 retrieval_status 与 rag_degraded 字段。"""
        _init_project(self.tmpdir)
        code, payload, proc = _run(EXECUTOR, [
            "continue-write", "--project-root", str(self.tmpdir),
            "--query", "主角在站台发现名单并与同伴发生冲突",
            "--allow-fallback-publish",
        ])
        self.assertIsNotNone(payload, f"输出非 JSON: {proc.stdout}")
        self.assertIn("retrieval_status", payload)
        self.assertIn(
            payload.get("retrieval_status"), {"success", "skipped", "failed"},
            f"retrieval_status 取值非法: {payload.get('retrieval_status')}",
        )
        self.assertIn("rag_degraded", payload)

    def test_rag_degraded_when_retrieval_fails(self):
        """检索持续失败（重建后仍失败）时：rag_degraded=True 且使用降级上下文。"""
        sys.path.insert(0, str(SCRIPTS_DIR))
        import novel_flow_executor as nfe

        _init_project(self.tmpdir)

        original_run_python = nfe.run_python

        def fake_run_python(script, args, *a, **kw):
            if "plot_rag_retriever.py" in str(script) and "query" in args:
                return 1, "", "simulated retrieval crash", None
            return original_run_python(script, args, *a, **kw)

        argv_backup = sys.argv
        sys.argv = [
            "prog", "continue-write",
            "--project-root", str(self.tmpdir),
            "--query", "主角在站台发现名单并与同伴发生冲突",
            "--allow-fallback-publish", "--force-run",
            "--no-auto-improve", "--no-auto-retry", "--no-graph-update",
        ]
        nfe.run_python = fake_run_python
        try:
            args = nfe.parse_args()
            result = nfe.continue_write(args)
        finally:
            nfe.run_python = original_run_python
            sys.argv = argv_backup

        self.assertEqual(
            result.get("retrieval_status"), "failed",
            f"检索持续失败时 retrieval_status 应为 failed: {result.get('retrieval_status')}",
        )
        self.assertTrue(
            result.get("rag_degraded"),
            "检索失败且无法恢复时必须置 rag_degraded=True",
        )


class TestFTS5Engine(unittest.TestCase):
    """步骤7/8：FTS5 片段级索引引擎与 --engine 双轨。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rag_fts5_"))
        (self.tmpdir / "00_memory" / "retrieval").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "03_manuscript").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "00_memory" / "character_tracker.md").write_text(
            "| 姓名 | 当前状态 |\n| --- | --- |\n| 张三 | 存活 |\n",
            encoding="utf-8",
        )
        (self.tmpdir / "03_manuscript" / "第1章-开篇.md").write_text(
            "# 第1章 开篇\n\n"
            + "张三走进临海港的旧站台，风里带着铁锈味。他翻开笔记本，"
              "把失踪名单上的名字又核对了一遍。\n\n" * 8,
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fts5_build_and_query(self):
        code, payload, proc = _run(RETRIEVER, [
            "build", "--project-root", str(self.tmpdir), "--engine", "fts5",
        ])
        self.assertEqual(code, 0, f"FTS5 build 失败: {proc.stderr}")
        self.assertTrue(payload and payload.get("ok"))
        db = self.tmpdir / "00_memory" / "retrieval" / "story_index.sqlite"
        self.assertTrue(db.exists(), "FTS5 索引库应生成 story_index.sqlite")

        code2, payload2, proc2 = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "张三在站台发现名单并与人发生冲突",
            "--engine", "fts5", "--auto-build",
        ])
        self.assertEqual(code2, 0, f"FTS5 query 失败: {proc2.stderr}")
        self.assertIsNotNone(payload2, f"输出非 JSON: {proc2.stdout}")
        result = payload2.get("result") or {}
        self.assertFalse(result.get("skipped", True), "含角色名的查询不应被跳过")
        retrieved = result.get("retrieved") or []
        self.assertTrue(retrieved, "FTS5 检索应命中章节")
        self.assertEqual(retrieved[0].get("chapter_file"), "第1章-开篇.md")
        passages = retrieved[0].get("passages") or []
        self.assertTrue(passages and passages[0].get("text"), "FTS5 应返回片段级结果")
        self.assertIn("retrieval_stats", result)

    def test_fts5_skips_stub_chapters(self):
        stub = self.tmpdir / "03_manuscript" / "第2章-占位.md"
        stub.write_text("# 第2章\n\n<!-- NOVEL_FLOW_STUB -->\n\n[待写]\n", encoding="utf-8")
        code, payload, proc = _run(RETRIEVER, [
            "build", "--project-root", str(self.tmpdir), "--engine", "fts5",
        ])
        self.assertEqual(code, 0, proc.stderr)
        self.assertTrue(payload.get("ok"))
        self.assertGreaterEqual(payload.get("skipped_stubs", 0), 1,
                                "占位章应被 FTS5 构建跳过")
        code2, payload2, proc2 = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "张三在站台发现名单并与人发生冲突",
            "--engine", "fts5",
        ])
        result = payload2.get("result") or {}
        files = [r.get("chapter_file") for r in (result.get("retrieved") or [])]
        self.assertNotIn("第2章-占位.md", files, "占位章不得进入 FTS5 索引")

    def test_fts5_and_legacy_find_same_chapter(self):
        _run(RETRIEVER, ["build", "--project-root", str(self.tmpdir), "--engine", "legacy"])
        _, lp, _ = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "张三在站台发现名单并与人发生冲突", "--engine", "legacy",
        ])
        _run(RETRIEVER, ["build", "--project-root", str(self.tmpdir), "--engine", "fts5"])
        _, fp, _ = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "张三在站台发现名单并与人发生冲突", "--engine", "fts5",
        ])
        lfiles = [r.get("chapter_file") for r in (lp.get("result") or {}).get("retrieved", [])]
        ffiles = [r.get("chapter_file") for r in (fp.get("result") or {}).get("retrieved", [])]
        self.assertIn("第1章-开篇.md", lfiles, "legacy 引擎应命中第1章")
        self.assertIn("第1章-开篇.md", ffiles, "FTS5 引擎应命中第1章")

    def test_executor_forwards_fts5_engine(self):
        _init_project(self.tmpdir)
        code, payload, proc = _run(EXECUTOR, [
            "continue-write", "--project-root", str(self.tmpdir),
            "--query", "主角在站台发现名单并与同伴发生冲突",
            "--allow-fallback-publish", "--retrieval-engine", "fts5",
        ])
        self.assertIsNotNone(payload, f"输出非 JSON: {proc.stdout}")
        db = self.tmpdir / "00_memory" / "retrieval" / "story_index.sqlite"
        self.assertTrue(
            db.exists(),
            "executor 应把 --retrieval-engine fts5 转发给检索脚本（应生成 story_index.sqlite）",
        )


class TestContextAssembler(unittest.TestCase):
    """步骤9：ContextAssembler 统一聚合三套记忆系统。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rag_asm_"))
        (self.tmpdir / "00_memory").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "03_manuscript").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "00_memory" / "character_tracker.md").write_text(
            "| 姓名 | 当前状态 |\n| --- | --- |\n| 张三 | 存活 |\n",
            encoding="utf-8",
        )
        (self.tmpdir / "00_memory" / "foreshadowing_tracker.md").write_text(
            "# 伏笔追踪器\n\n"
            "## 🔴 紧急回收\n| ID | 伏笔内容 | 埋设章节 | 预期回收 | 当前章节 | 超期章数 |\n"
            "|----|---------|---------|---------|---------|---------|\n"
            "| F1-003 | 码头铁箱 | 第1章 | 第8章 | 第9章 | 1 |\n\n"
            "## 🟡 活跃伏笔\n| ID | 伏笔内容 | 埋设章节 | 预期回收 | 关联剧情 | 回收方式提示 |\n"
            "|----|---------|---------|---------|---------|-----------|\n"
            "| F1-001 | A17坐标的秘密 | 第1章 | 第90章 | 失踪案 | 主角再访旧站台 |\n",
            encoding="utf-8",
        )
        (self.tmpdir / "00_memory" / "novel_plan.md").write_text(
            "# 主线计划\n\n主角调查旧港区失踪案。\n", encoding="utf-8",
        )
        (self.tmpdir / "00_memory" / "world_state.md").write_text(
            "# 世界状态追踪\n\n## 势力分布\n| 势力名 | 实力等级 | 与主角关系 | 当前状态 |\n"
            "|--------|---------|-----------|---------|\n| 港务局 | 中 | 可疑 | 监视主角 |\n",
            encoding="utf-8",
        )
        (self.tmpdir / "03_manuscript" / "第1章-开篇.md").write_text(
            "# 第1章 开篇\n\n张三走进临海港的旧站台，风里带着铁锈味。"
            "他翻开笔记本，把失踪名单上的名字又核对了一遍。\n\n" * 8,
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_assembler_collects_all_sections(self):
        """assemble() 应聚合 前情/角色/线索/世界/伏笔 等全部 section。"""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from context_assembler import ContextAssembler

        assembled = ContextAssembler(self.tmpdir, chapter_no=2).assemble()
        expected = {
            "recent_chapters", "character_states", "plot_threads",
            "world_state", "foreshadows", "graph", "rag", "warnings",
        }
        self.assertTrue(
            expected.issubset(set(assembled.sections.keys())),
            f"缺少 section: {expected - set(assembled.sections.keys())}",
        )
        self.assertIn("A17坐标", assembled.prompt, "prompt 应包含活跃伏笔内容")
        self.assertIn("张三", assembled.sections.get("character_states", ""), "角色状态段应含角色名")

    def test_assembler_includes_rag_and_graph(self):
        """传入 rag_result 与 graph_context 时应注入 RAG 片段与图谱事实。"""
        sys.path.insert(0, str(SCRIPTS_DIR))
        from context_assembler import ContextAssembler

        rag_result = {
            "retrieved": [{
                "chapter_file": "第1章-开篇.md",
                "passages": [{"text": "张三在旧站台核对名单，注意到铁箱"},
                              {"text": "另一段历史片段"}],
            }]
        }
        graph_context = {"ok": True, "context_prompt": "图谱事实：张三与港务局为敌对关系。"}
        assembled = ContextAssembler(
            self.tmpdir, chapter_no=2,
            rag_result=rag_result, graph_context=graph_context,
        ).assemble()
        self.assertIn("张三在旧站台核对名单", assembled.prompt, "RAG 片段未注入")
        self.assertIn("敌对关系", assembled.prompt, "图谱事实未注入")
        self.assertIn("港务局", assembled.sections.get("world_state", ""), "世界状态未注入")

    def test_continue_write_records_context_assembler(self):
        """continue-write 结果应记录 context_assembler 聚合信息。"""
        _init_project(self.tmpdir)
        code, payload, proc = _run(EXECUTOR, [
            "continue-write", "--project-root", str(self.tmpdir),
            "--query", "主角在站台发现名单并与同伴发生冲突",
            "--allow-fallback-publish",
        ])
        self.assertIsNotNone(payload, f"输出非 JSON: {proc.stdout}")
        info = payload.get("context_assembler") or {}
        self.assertTrue(info.get("enabled"), f"context_assembler 应默认启用: {info}")
        self.assertTrue(info.get("sections"), f"context_assembler 应产出 sections: {info}")

    def test_no_context_assembler_flag_disables(self):
        """--no-context-assembler 应关闭聚合。"""
        _init_project(self.tmpdir)
        code, payload, proc = _run(EXECUTOR, [
            "continue-write", "--project-root", str(self.tmpdir),
            "--query", "主角在站台发现名单并与同伴发生冲突",
            "--allow-fallback-publish", "--no-context-assembler",
        ])
        self.assertIsNotNone(payload)
        info = payload.get("context_assembler") or {}
        self.assertFalse(info.get("enabled"), "--no-context-assembler 应关闭聚合")


class TestAliasAndGraphRecall(unittest.TestCase):
    """步骤10：角色别名召回 + 知识图谱邻接召回。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="rag_alias_"))
        (self.tmpdir / "00_memory" / "retrieval").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "03_manuscript").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "00_memory" / "character_tracker.md").write_text(
            "| 姓名 | 当前状态 | 别名 |\n"
            "| --- | --- | --- |\n"
            "| 张三 | 存活 | 老张、张队 |\n"
            "| 李四 | 存活 | 老四 |\n",
            encoding="utf-8",
        )
        # 第1章正文用别名"老张"称呼（测试 build 端别名归一）
        (self.tmpdir / "03_manuscript" / "第1章-开篇.md").write_text(
            "# 第1章 开篇\n\n"
            "老张走进临海港的旧站台，风里带着铁锈味。他翻开笔记本，"
            "把失踪名单上的名字又核对了一遍。\n\n" * 8,
            encoding="utf-8",
        )
        # 第2章与查询词面零重叠，仅靠图谱邻居（张三↔李四）应被召回
        (self.tmpdir / "03_manuscript" / "第2章-仓库.md").write_text(
            "# 第2章 仓库\n\n"
            "李四在仓库搬运货物，把铁箱锁好，然后离开了。\n\n" * 8,
            encoding="utf-8",
        )
        (self.tmpdir / "00_memory" / "story_graph.json").write_text(
            json.dumps({
                "nodes": [
                    {"id": "char_zs", "name": "张三", "type": "character"},
                    {"id": "char_ls", "name": "李四", "type": "character"},
                ],
                "edges": [
                    {"type": "ally", "source": "char_zs", "target": "char_ls"},
                ],
            }, ensure_ascii=False),
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_alias_trigger_activates_retrieval(self):
        """查询只含别名（老张）时也应触发检索，而不是被当作轻场景跳过。"""
        code, payload, proc = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "老张调查名单", "--auto-build", "--engine", "legacy",
        ])
        self.assertIsNotNone(payload, f"输出非 JSON: {proc.stdout} {proc.stderr}")
        result = payload.get("result") or {}
        self.assertFalse(
            result.get("skipped", True),
            f"别名命中应触发检索，实际被跳过: {result.get('trigger_reason')}",
        )

    def test_alias_query_recalls_character_chapter(self):
        """用别名（老张）查询应召回正名（张三）所在的章节。

        查询与正文词面零重叠（正文用"老张"称呼），召回只能依赖
        别名归一链路：build 端别名→正名 + 查询端别名→正名扩展。
        """
        code, payload, proc = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "老张独自调查旧案",
            "--auto-build", "--engine", "legacy",
        ])
        self.assertIsNotNone(payload)
        result = payload.get("result") or {}
        files = [r.get("chapter_file") for r in (result.get("retrieved") or [])]
        self.assertIn("第1章-开篇.md", files, "别名（老张）应召回张三所在章节")

    def test_graph_neighbor_recalls_chapter(self):
        """查询实体张三时，图谱邻居李四所在的章节应被召回（词面零重叠）。"""
        code, payload, proc = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "张三在站台发现名单并与人发生冲突",
            "--auto-build", "--engine", "legacy",
        ])
        self.assertIsNotNone(payload)
        result = payload.get("result") or {}
        files = [r.get("chapter_file") for r in (result.get("retrieved") or [])]
        self.assertIn("第2章-仓库.md", files, "图谱邻居（李四）所在章节应被召回")

    def test_alias_works_in_fts5_engine(self):
        """FTS5 引擎同样支持别名召回。"""
        code, payload, proc = _run(RETRIEVER, [
            "query", "--project-root", str(self.tmpdir),
            "--query", "老张独自调查旧案",
            "--auto-build", "--engine", "fts5",
        ])
        self.assertIsNotNone(payload, f"输出非 JSON: {proc.stdout} {proc.stderr}")
        result = payload.get("result") or {}
        files = [r.get("chapter_file") for r in (result.get("retrieved") or [])]
        self.assertIn("第1章-开篇.md", files, "FTS5 引擎别名（老张）应召回张三章节")


if __name__ == "__main__":
    unittest.main()
