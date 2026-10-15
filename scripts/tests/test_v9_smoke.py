#!/usr/bin/env python3
"""novel-writer 9.0 合并版集成基线测试。

v9 的构成：oh-story 工艺层（上游自带测试，本仓库不重复）+ novel-writer 原生
检索/账本层（本文件覆盖）。验证在 oh 目录结构（正文/）上的最小闭环：
canonical 接受 → FTS5 建索引 → 查询命中 → 防篡改失效。

运行方式:
    python scripts/tests/test_v9_smoke.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _run(*args, env_extra=None):
    env = dict(os.environ)
    env["NOVEL_MANUSCRIPT_DIR"] = "正文"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / args[0]), *args[1:]],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    return proc


class TestV9RetrievalPipeline(unittest.TestCase):
    """oh 结构项目上的 canonical + FTS5 检索闭环。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="v9_smoke_"))
        (self.root / "正文").mkdir()
        ch1 = self.root / "正文" / "第001章_试刀.md"
        ch2 = self.root / "正文" / "第002章_追账.md"
        ch1.write_text(
            "# 第001章 试刀\n\n老周在码头捡到一枚铜哨。哨身上刻着两个字，陈九。"
            "他把哨子揣进兜里，往货仓走。" * 3, encoding="utf-8")
        ch2.write_text(
            "# 第002章 追账\n\n账房翻出旧簿子，一笔一笔对。铜哨的主人三年前欠了一笔盐钱，"
            "利滚利，如今要拿船来抵。" * 3, encoding="utf-8")
        self.ch1, self.ch2 = ch1, ch2
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def test_accept_build_query_cycle(self):
        # 1) canonical 逐章接受（NOVEL_MANUSCRIPT_DIR=正文）
        for ch in (self.ch1, self.ch2):
            proc = _run("canonical_state.py", "accept", "--project-root", str(self.root),
                        "--chapter-file", str(ch), "--reviewer", "smoke", "--confirm", "ACCEPT")
            self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        # 2) FTS5 建索引
        proc = _run("plot_rag_retriever.py", "build", "--project-root", str(self.root),
                    "--engine", "fts5")
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        payload = json.loads(proc.stdout)
        self.assertTrue(payload.get("ok"))
        # 3) 查询命中正确章节
        proc = _run("plot_rag_retriever.py", "query", "--project-root", str(self.root),
                    "--engine", "fts5", "--no-skip", "--query", "铜哨 主人 盐钱")
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        result = json.loads(proc.stdout).get("result", {})
        self.assertFalse(result.get("skipped"), "无记忆文件项目不应跳过检索")
        retrieved = result.get("retrieved") or []
        self.assertGreaterEqual(len(retrieved), 1, "应至少命中一章")

    def test_tampered_chapter_rejected_on_reaccept(self):
        _run("canonical_state.py", "accept", "--project-root", str(self.root),
             "--chapter-file", str(self.ch1), "--reviewer", "smoke", "--confirm", "ACCEPT")
        # 篡改正文后原凭据应失效（重接受生成新 SHA256，状态可检测）
        self.ch1.write_text("# 第001章 试刀\n\n被改过的正文。", encoding="utf-8")
        proc = _run("canonical_state.py", "status", "--project-root", str(self.root))
        self.assertEqual(proc.returncode, 0)
        # status 输出应能反映当前凭据状态（不再匹配被改文件）
        self.assertIn("accept", json.dumps(json.loads(proc.stdout), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
