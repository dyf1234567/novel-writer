"""Default creative heuristics stay advisory; safety and explicit strict mode remain."""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chapter_gate_check import check_quality_report
from novel_flow_executor import evaluate_quality, parse_args, write_quality_report


class OptionalDefaultTests(unittest.TestCase):
    def test_continue_write_defaults_to_smallest_workflow(self):
        with patch.object(sys, "argv", ["novel_flow_executor.py", "continue-write",
                                        "--project-root", "project"]):
            args = parse_args()
        self.assertFalse(args.strict_prose_metrics)
        self.assertFalse(args.use_beat_sheet)
        self.assertFalse(args.auto_research)
        self.assertFalse(args.auto_batch_review)
        self.assertFalse(args.four_official_audit)
        self.assertFalse(args.auto_style_update)
        self.assertTrue(args.human_checkpoints)
        self.assertTrue(args.checkpoint_require_volume_audit)

    def test_metrics_are_visible_but_not_blocking_by_default(self):
        kwargs = dict(min_chars=500, min_paragraphs=8, min_dialogue_ratio=0.1,
                      max_dialogue_ratio=0.7, min_sentences=8, pacing_mode="standard")
        text = "# 第一章\n\n一段安静而完整的短场景。"
        advisory = evaluate_quality(text, argparse.Namespace(**kwargs, strict_prose_metrics=False))
        strict = evaluate_quality(text, argparse.Namespace(**kwargs, strict_prose_metrics=True))
        self.assertTrue(advisory["passed"])
        self.assertEqual(advisory["failures"], [])
        self.assertTrue(advisory["metric_signals"])
        self.assertFalse(strict["passed"])
        self.assertTrue(strict["failures"])

        with tempfile.TemporaryDirectory() as tmp:
            report = write_quality_report(Path(tmp), advisory, advisory)
            self.assertTrue(check_quality_report(report)[0])
            strict_report = write_quality_report(Path(tmp), strict, strict)
            self.assertFalse(check_quality_report(strict_report)[0])

    def test_old_reports_keep_strict_interpretation(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "quality_report.md"
            report.write_text("- 段落唯一比例：0.5\n- 最大重复段落次数：4\n- 通过：True\n",
                              encoding="utf-8")
            ok, reason = check_quality_report(report)
            self.assertFalse(ok)
            self.assertIn("段落重复度", reason)


if __name__ == "__main__":
    unittest.main()
