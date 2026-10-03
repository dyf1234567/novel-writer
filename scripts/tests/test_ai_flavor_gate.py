#!/usr/bin/env python3
"""去AI味铁律门禁测试（ai_flavor_gate）

覆盖三层：
1. check_ai_flavor 函数级判定（轻微通过；中等/严重/缺失阻断）；
2. gate_repair_plan 对 ai_flavor_gate 失败前缀的最短修复路径；
3. chapter_gate_check.py 主流程集成（failures 含 ai_flavor_gate）。

运行方式:
    python scripts/tests/test_ai_flavor_gate.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from chapter_gate_check import check_ai_flavor  # noqa: E402
from gate_repair_plan import map_failure_to_steps  # noqa: E402


class TestCheckAiFlavor(unittest.TestCase):
    """函数级：copyedit_report.md 结论行的四种判定。"""

    def _write(self, content: str) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="ai_flavor_"))
        p = tmp / "copyedit_report.md"
        p.write_text(content, encoding="utf-8")
        self.addCleanup(lambda: _rmtree(tmp))
        return p

    def test_minor_passes(self):
        ok, msg = check_ai_flavor(self._write("# 校稿报告\n\n- AI痕迹严重程度：轻微\n" + "x" * 100))
        self.assertTrue(ok)

    def test_medium_blocks(self):
        ok, _ = check_ai_flavor(self._write("# 校稿报告\n\n- AI痕迹严重程度：中等\n" + "x" * 100))
        self.assertFalse(ok)

    def test_severe_blocks(self):
        ok, _ = check_ai_flavor(self._write("# 报告\n\nAI痕迹严重程度：**严重**\n" + "x" * 100))
        self.assertFalse(ok)

    def test_unknown_blocks(self):
        ok, _ = check_ai_flavor(self._write("# 报告\n\n- AI痕迹严重程度：未知\n" + "x" * 100))
        self.assertFalse(ok)

    def test_missing_conclusion_blocks(self):
        ok, msg = check_ai_flavor(self._write("# 校稿报告\n\n- 无检测信息\n" + "x" * 100))
        self.assertFalse(ok)
        self.assertIn("缺少", msg)


class TestRepairPlanIntegration(unittest.TestCase):
    """gate_repair_plan 必须为 ai_flavor_gate 给出针对性修复路径。"""

    def test_unknown_failure_gets_rerun_advice(self):
        steps = map_failure_to_steps(
            "ai_flavor_gate: copyedit_report.md 缺少「AI痕迹严重程度」结论，去AI味检测未执行"
        )
        joined = "\n".join(steps)
        self.assertIn("未执行", joined)
        self.assertIn("/继续写", joined)

    def test_medium_failure_gets_polish_advice(self):
        steps = map_failure_to_steps(
            "ai_flavor_gate: AI痕迹严重程度为「中等」，未完成两遍式去AI味润色，"
            "违反每章强制闭环铁律"
        )
        joined = "\n".join(steps)
        self.assertIn("/校稿", joined)
        self.assertIn("NOVEL_LLM_PROVIDER", joined)


class TestGateIntegration(unittest.TestCase):
    """集成级：完整跑 chapter_gate_check.py 主流程。"""

    def _build_project(self, severity_line: str):
        root = Path(tempfile.mkdtemp(prefix="ai_gate_e2e_"))
        self.addCleanup(lambda: _rmtree(root))
        gate = root / "04_editing" / "gate_artifacts" / "第1章-测试"
        gate.mkdir(parents=True)
        (root / "03_manuscript").mkdir()
        chapter = root / "03_manuscript" / "第1章-测试.md"
        chapter.write_text("第1章\n\n" + "他推门进去，屋里没人。" * 40, encoding="utf-8")

        filler = "x" * 200
        (gate / "memory_update.md").write_text("# 报告\n结论：通过\n" + filler, encoding="utf-8")
        (gate / "consistency_report.md").write_text("# 报告\n结论：通过\n" + filler, encoding="utf-8")
        (gate / "style_calibration.md").write_text("# 报告\n结论：通过\n" + filler, encoding="utf-8")
        (gate / "publish_ready.md").write_text("结论：可发布（通过）\n" + filler, encoding="utf-8")
        (gate / "quality_report.md").write_text(
            "# 质量\n\n通过：True\n段落唯一比例：0.95\n最大重复段落次数：1\n" + "y" * 100,
            encoding="utf-8",
        )
        (gate / "copyedit_report.md").write_text(
            f"# 校稿报告\n\n- {severity_line}\n" + filler, encoding="utf-8"
        )
        return root, chapter

    def _run_gate(self, root: Path, chapter: Path) -> dict:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "chapter_gate_check.py"),
             "--project-root", str(root), "--chapter-file", str(chapter)],
            capture_output=True, text=True, encoding="utf-8",
        )
        return json.loads(proc.stdout)

    def test_medium_blocks_in_full_gate(self):
        root, chapter = self._build_project("AI痕迹严重程度：中等")
        payload = self._run_gate(root, chapter)
        self.assertFalse(payload["passed"])
        self.assertTrue(any(f.startswith("ai_flavor_gate") for f in payload["failures"]))

    def test_minor_does_not_block(self):
        root, chapter = self._build_project("AI痕迹严重程度：轻微")
        payload = self._run_gate(root, chapter)
        self.assertTrue(payload["passed"])
        item = [c for c in payload["checks"] if c["name"] == "ai_flavor_gate"]
        self.assertEqual(len(item), 1)
        self.assertTrue(item[0]["ok"])


def _rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
