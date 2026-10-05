"""Offline regression fixtures for draft/acceptance/polishing boundaries."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import ai_flavor_state as ai
import canonical_state as canon
import chapter_gate_check as gate
import novel_chapter_writer as writer
import novel_flow_executor as flow
import text_humanizer as humanizer

CLEAN = "她把书放回架子。门外传来脚步声。天已经亮了。\n\n" * 30
MEDIUM = "窗上的水珠仿佛细小的灯。与此同时，楼下的门开了。\n\n" + CLEAN
HIGH = ("他不禁感到一阵心悸。仿佛一切都映入眼帘。此时此刻，他心中暗道不妙。"
        "她嘴角微扬。他微微点了点头，淡淡地说道，这次会面意义深远，未来可期。"
        "不难看出，他已下定决心。与此同时，他缓缓转身，不由自主地叹了口气。") + CLEAN
REASON = "逐项复核：比喻与同时转场符合本书声音，命中词语并非重复套话，保留原表达。"


class ReviewSafeguards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "03_manuscript").mkdir()
        self.chapter = self.root / "03_manuscript/第1章-测试.md"
        self.chapter.write_text(CLEAN, encoding="utf-8")
        self.summary = self.root / "00_memory/chapter_summaries/recent.md"

    def test_writer_never_commits_draft_even_legacy_true(self):
        provider = SimpleNamespace(generate=lambda *_: HIGH)
        with patch.object(writer, "create_ai_provider", return_value=provider), contextlib.redirect_stdout(io.StringIO()):
            result = writer.write_chapter(self.root, self.chapter,
                                         {"ai_provider": "offline", "auto_update_memory": True,
                                          "skip_humanizer": True})
        self.assertTrue(result["ok"])
        self.assertEqual(result["memory_status"], "pending_acceptance")
        self.assertFalse(self.summary.exists())
        self.assertFalse(canon.accepted_files(self.root)[0])
        with self.assertRaises(ValueError):
            writer.update_memory_files(self.root, 1, HIGH, None)

    def test_manual_accept_scans_and_blocks_without_any_report(self):
        self.chapter.write_text(HIGH, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "待复核"):
            canon.accept_chapter(self.root, self.chapter, "reviewer")
        self.assertFalse(self.summary.exists())
        self.assertFalse(canon.accepted_files(self.root)[0])

    def test_spoofed_light_report_and_conflicting_labels_fail(self):
        self.chapter.write_text(HIGH, encoding="utf-8")
        report = self.root / "copyedit_report.md"
        report.write_text("AI痕迹严重程度：轻微", encoding="utf-8")
        self.assertFalse(gate.check_ai_flavor(report, self.chapter, self.root)[0])
        report.write_text("AI痕迹严重程度：轻微\nAI痕迹严重程度：严重", encoding="utf-8")
        self.assertFalse(gate.check_ai_flavor(report, self.chapter, self.root)[0])

    def test_false_positive_is_bound_to_body_and_detector_version(self):
        self.chapter.write_text(MEDIUM, encoding="utf-8")
        self.assertFalse(ai.check_chapter(self.root, self.chapter)["passed"])
        ai.record_false_positive(self.root, self.chapter, "作者", REASON)
        self.assertTrue(ai.check_chapter(self.root, self.chapter)["passed"])
        with patch.object(ai, "DETECTOR_VERSION", ai.DETECTOR_VERSION + 1):
            self.assertFalse(ai.check_chapter(self.root, self.chapter)["passed"])
        self.chapter.write_text(MEDIUM + "她打开窗户。", encoding="utf-8")
        self.assertFalse(ai.check_chapter(self.root, self.chapter)["passed"])

    def test_review_cli_requires_explicit_confirmation(self):
        self.chapter.write_text(MEDIUM, encoding="utf-8")
        argv = [sys.executable, str(SCRIPTS / "text_humanizer.py"), "review",
                "--project-root", str(self.root), "--chapter-file", str(self.chapter),
                "--reviewer", "作者", "--reason", REASON]
        denied = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(ai.review_path(self.root, self.chapter).exists())
        allowed = subprocess.run(argv + ["--confirm", "FALSE_POSITIVE"], capture_output=True,
                                 text=True, encoding="utf-8")
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertTrue(ai.check_chapter(self.root, self.chapter)["passed"])

    def test_accept_commits_once_and_revision_replaces_only_managed_block(self):
        self.summary.parent.mkdir(parents=True)
        self.summary.write_text("作者手写备注：勿删。\n", encoding="utf-8")
        record = canon.accept_chapter(self.root, self.chapter, "作者")
        self.assertTrue(record["memory"]["updated"])
        self.assertEqual(record["ai_flavor"]["chapter_sha256"], canon.digest(self.chapter))
        first = self.summary.read_bytes()
        canon.accept_chapter(self.root, self.chapter, "作者")
        self.assertEqual(first, self.summary.read_bytes())
        self.chapter.write_text("她换上新的银铃，走向码头。", encoding="utf-8")
        self.assertFalse(canon.acceptance(self.root, self.chapter)[0])
        with self.assertRaises(ValueError):
            canon.commit_accepted_memory(self.root, self.chapter)
        canon.accept_chapter(self.root, self.chapter, "作者")
        text = self.summary.read_text(encoding="utf-8")
        self.assertIn("作者手写备注：勿删。", text)
        self.assertIn("新的银铃", text)
        self.assertNotIn("她把书放回架子", text)
        self.assertEqual(text.count("<!-- accepted-summary:1 -->"), 1)

    def test_revising_older_chapter_does_not_rewind_progress(self):
        state = self.root / "00_memory/novel_state.md"
        state.parent.mkdir()
        state.write_text("当前章节：第0章\n其他记录保留。", encoding="utf-8")
        second = self.chapter.with_name("第2章-归途.md")
        second.write_text(CLEAN, encoding="utf-8")
        canon.accept_chapter(self.root, second, "作者")
        canon.accept_chapter(self.root, self.chapter, "作者")
        self.assertIn("当前章节：第2章", state.read_text(encoding="utf-8"))

    def test_memory_failure_is_disclosed_and_retry_is_idempotent(self):
        with patch.object(canon, "_atomic_text", side_effect=PermissionError("fixture")):
            result = canon.accept_chapter(self.root, self.chapter, "作者")
        self.assertTrue(canon.acceptance(self.root, self.chapter)[0])
        self.assertFalse(result["memory"]["updated"])
        self.assertTrue(canon.accept_chapter(self.root, self.chapter, "作者")["memory"]["updated"])

    def test_polishing_retests_medium_and_regenerates_quality_with_cli_config(self):
        self.chapter.write_text(HIGH, encoding="utf-8")
        quality = {"passed": True, "char_count": 820, "strict_prose_metrics": False}
        calls = []

        def fake_writer(*_, **kwargs):
            calls.append(kwargs["config_overrides"])
            self.chapter.write_text(MEDIUM, encoding="utf-8")
            return {"ok": True}

        args = SimpleNamespace(llm_provider="offline", llm_model="chosen-model", llm_api_key="dummy",
                               min_chars=10, min_paragraphs=1, min_dialogue_ratio=0,
                               max_dialogue_ratio=1, min_sentences=1, strict_prose_metrics=False)
        with patch.object(writer, "write_chapter", side_effect=fake_writer), \
                patch.dict(os.environ, {"NOVEL_LLM_PROVIDER": "wrong"}):
            flow.write_gate_artifacts(self.root, self.chapter, "核对", quality, None, args)
        folder = ai.review_path(self.root, self.chapter).parent
        report = (folder / "copyedit_report.md").read_text(encoding="utf-8")
        self.assertIn("AI痕迹严重程度：中等", report)
        self.assertNotIn("AI痕迹严重程度：严重", report)
        self.assertEqual(quality["char_count"], flow.evaluate_quality(MEDIUM, args)["char_count"])
        for name in ("quality_report", "copyedit_report", "memory_update", "consistency_report",
                     "style_calibration", "publish_ready"):
            artifact = folder / f"{name}.md"
            self.assertGreaterEqual(artifact.stat().st_mtime_ns, self.chapter.stat().st_mtime_ns)
        self.assertEqual(len(calls), 2)
        for config in calls:
            self.assertEqual(config["ai_provider"], "offline")
            self.assertEqual(config["model"], "chosen-model")
            self.assertFalse(config["auto_update_memory"])
            self.assertTrue(config["skip_humanizer"])
        self.assertFalse(self.summary.exists())
        self.assertFalse(json.loads((folder / "ai_flavor_scan.json").read_text(encoding="utf-8"))["passed"])

    def test_reviewed_intentional_style_is_not_automatically_rewritten(self):
        self.chapter.write_text(MEDIUM, encoding="utf-8")
        ai.record_false_positive(self.root, self.chapter, "作者", REASON)
        with patch.object(writer, "write_chapter") as model:
            flow.write_gate_artifacts(self.root, self.chapter, "核对", {}, None)
        model.assert_not_called()
        self.assertEqual(self.chapter.read_text(encoding="utf-8"), MEDIUM)
        self.assertTrue(ai.check_chapter(self.root, self.chapter)["passed"])

    def test_successful_polish_accepts_final_body_and_current_reports(self):
        self.chapter.write_text(HIGH, encoding="utf-8")
        args = SimpleNamespace(llm_provider="offline", min_chars=10, min_paragraphs=1,
                               min_dialogue_ratio=0, max_dialogue_ratio=1, min_sentences=1,
                               strict_prose_metrics=False)
        quality = flow.evaluate_quality(HIGH, args)

        def fake_writer(*_, **kwargs):
            self.chapter.write_text(CLEAN, encoding="utf-8")
            return {"ok": True}

        with patch.object(writer, "write_chapter", side_effect=fake_writer):
            flow.write_gate_artifacts(self.root, self.chapter, "核对", quality, None, args)
        code, result = flow.run_gate_check(self.root, self.chapter)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ai_flavor"]["passed"])
        record = canon.accept_chapter(self.root, self.chapter, "pipeline", source="pipeline")
        self.assertTrue(record["memory"]["updated"])
        text = self.summary.read_text(encoding="utf-8")
        self.assertIn("她把书放回架子", text)
        self.assertNotIn("他不禁", text)

    def test_polish_uses_project_model_without_legacy_provider_env(self):
        self.chapter.write_text(HIGH, encoding="utf-8")
        (self.root / ".novel_writer_config.yaml").write_text(json.dumps({
            "ai_provider": "offline", "model": "project-model", "auto_update_memory": True,
        }), encoding="utf-8")
        configs = []

        def create_provider(config):
            configs.append(config)
            return SimpleNamespace(generate=lambda *_: CLEAN)

        with patch.dict(os.environ, {}, clear=True), patch.object(writer, "create_ai_provider", side_effect=create_provider):
            flow.write_gate_artifacts(self.root, self.chapter, "核对", {}, None)
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0]["ai_provider"], "offline")
        self.assertEqual(configs[0]["model"], "project-model")
        self.assertFalse(configs[0]["auto_update_memory"])
        self.assertFalse(self.summary.exists())


if __name__ == "__main__":
    unittest.main()
