#!/usr/bin/env python3
"""8.1.1 审计修复回归测试

锚定四个修复的行为，防止回退：
1. improve_text_minimally 为 no-op——正文不得被指令文本/拼装上下文污染；
2. check_publish_ready 失败标记优先——「不通过」不再被成功词「通过」
   子串误判为通过；
3. continue_write 无 UnboundLocalError——persona_setup 警告进入输出 JSON
   的 warnings（新项目人格层未建立时必现）；
4. MCP Codex 免密钥路径已删除——_has_llm_config 不再因环境变量
   CODEX_MODE/CLAUDE_CODE_MODE 返回 True。

运行方式:
    python scripts/tests/test_bugfix_regressions.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from chapter_gate_check import check_publish_ready  # noqa: E402
from novel_flow_executor import improve_text_minimally  # noqa: E402


class TestImproveNoOp(unittest.TestCase):
    """修复 1：机械补写不再污染正文。"""

    def test_returns_text_unchanged_even_with_huge_context(self):
        text = "他推门进去，屋里没人。"
        huge_query = "章纲" * 2000 + "检索片段" * 2000
        result = improve_text_minimally(text, huge_query)
        self.assertEqual(result, text)

    def test_no_instruction_text_leaks(self):
        result = improve_text_minimally("正文。", "目标")
        self.assertNotIn("补充推进", result)
        self.assertNotIn("行动结果", result)


class TestPublishReadyFailFirst(unittest.TestCase):
    """修复 3：publish_ready 失败标记优先。"""

    KEYWORDS = ["可发布", "通过", "PASS"]

    def _check(self, content: str):
        import shutil
        tmp = Path(tempfile.mkdtemp(prefix="pub_"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        p = tmp / "publish_ready.md"
        p.write_text(content, encoding="utf-8")
        return check_publish_ready(p, self.KEYWORDS)

    def test_failure_text_rejected(self):
        # 修复前：返回 (True, '命中发布关键字: 通过')——「通过」是「不通过」子串
        ok, _ = self._check("结论：不建议发布（未通过）\n关键词：不通过 / FAIL")
        self.assertFalse(ok)

    def test_fail_marker_alone_rejected(self):
        ok, _ = self._check("结论：不建议发布")
        self.assertFalse(ok)

    def test_success_text_accepted(self):
        ok, _ = self._check("结论：可发布（通过）\n关键词：可发布 / 通过 / PASS")
        self.assertTrue(ok)

    def test_no_keyword_rejected(self):
        ok, _ = self._check("本章还没有发布判定。")
        self.assertFalse(ok)


class TestMcpPathRemoved(unittest.TestCase):
    """修复 4：CODEX_MODE 环境变量不再伪造 LLM 可用。"""

    def test_has_llm_config_ignores_codex_mode(self):
        import novel_flow_executor as nfe
        import argparse

        tmp = Path(tempfile.mkdtemp(prefix="mcp_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        args = argparse.Namespace(llm_provider=None, llm_api_key=None)
        old = {k: os.environ.get(k) for k in ("CODEX_MODE", "CLAUDE_CODE_MODE",
                                              "NOVEL_LLM_PROVIDER", "NOVEL_AI_PROVIDER")}
        try:
            os.environ["CODEX_MODE"] = "1"
            os.environ["CLAUDE_CODE_MODE"] = "1"
            os.environ.pop("NOVEL_LLM_PROVIDER", None)
            os.environ.pop("NOVEL_AI_PROVIDER", None)
            self.assertFalse(nfe._has_llm_config(args, tmp))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_mcp_function_and_flag_removed(self):
        import novel_flow_executor as nfe
        self.assertFalse(hasattr(nfe, "_write_with_mcp_codex"))
        self.assertFalse(hasattr(nfe, "_CLAUDE_CODE_MODE"))


class TestContinueWriteNoUnboundLocal(unittest.TestCase):
    """修复 2：实跑 continue-write，风格段不再 UnboundLocalError。

    新项目人格层未建立是 persona 分支的必经路径（修复前每次触发）。
    """

    def test_fresh_project_run_has_no_style_error(self):
        root = Path(tempfile.mkdtemp(prefix="cw_e2e_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))

        def run(*cli_args):
            proc = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "novel_flow_executor.py"), *cli_args],
                capture_output=True, text=True, encoding="utf-8",
            )
            return json.loads(proc.stdout)

        run("one-click", "--project-root", str(root),
            "--title", "回归", "--genre", "都市", "--idea", "主角发现失踪名单")
        payload = run("continue-write", "--project-root", str(root),
                      "--query", "主角在码头仓库找到记号")

        sfs = payload.get("style_fewshot") or {}
        self.assertNotIn(
            "UnboundLocalError", str(sfs.get("error", "")),
            f"风格段仍触发 UnboundLocalError: {sfs}",
        )
        warnings = payload.get("warnings") or []
        self.assertTrue(
            any(str(w).startswith("persona_setup") for w in warnings),
            f"persona_setup 警告未进入 JSON warnings: {warnings}",
        )


if __name__ == "__main__":
    unittest.main()
