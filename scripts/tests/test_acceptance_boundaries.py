"""Cross-step acceptance, cache and retry-budget regressions (offline only)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import canonical_state as canon
import novel_chapter_writer as writer
import novel_flow_executor as flow
from long_term_context_manager import LongTermContextManager
from plot_rag_retriever import build_index

CLEAN = "她把书放回架子。门外传来脚步声。天已经亮了。\n\n" * 30
HIGH = ("他不禁感到一阵心悸。仿佛一切都映入眼帘。此时此刻，他心中暗道不妙。"
        "她嘴角微扬。他微微点了点头，淡淡地说道，这次会面意义深远，未来可期。"
        "不难看出，他已下定决心。与此同时，他缓缓转身，不由自主地叹了口气。") + CLEAN


class AcceptanceBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "03_manuscript").mkdir()
        self.chapter = self.root / "03_manuscript/第0001章-测试.md"
        self.chapter.write_text(CLEAN, encoding="utf-8")

    def args(self, *extra, retry=False):
        argv = ["flow", "continue-write", "--project-root", str(self.root),
                "--chapter-file", str(self.chapter), "--query", "核对",
                "--no-auto-draft", "--no-auto-improve"]
        if not retry:
            argv.append("--no-auto-retry")
        with patch.object(sys, "argv", argv + list(extra)):
            return flow.parse_args()

    def test_writer_reads_only_accepted_unchanged_chapters(self):
        extractor = writer.ContextExtractor(self.root)
        self.assertEqual(extractor.get_previous_chapters(2), [])
        canon.accept_chapter(self.root, self.chapter, "作者")
        self.assertEqual(len(extractor.get_previous_chapters(2)), 1)
        self.chapter.write_text(CLEAN + "未接受的修改。", encoding="utf-8")
        self.assertEqual(extractor.get_previous_chapters(2), [])

    def test_long_body_retains_chapter_number_and_padded_name(self):
        canon.accept_chapter(self.root, self.chapter, "作者")
        result = writer.ContextExtractor(self.root).get_previous_chapters(2)
        self.assertEqual(result[0]["chapter_no"], 1)
        self.assertEqual(result[0]["file"], str(self.chapter))

    def test_ghost_metadata_and_stale_index_do_not_supply_summaries(self):
        manager = LongTermContextManager(self.root)
        meta = self.root / "00_memory/retrieval/chapter_meta/ch0001.meta.json"
        meta.parent.mkdir()
        meta.write_text(json.dumps({"summary": "幽灵草稿线索"}), encoding="utf-8")
        self.assertEqual(manager._get_recent_chapter_summaries(2, 5), [])
        canon.accept_chapter(self.root, self.chapter, "作者")
        result = manager._get_recent_chapter_summaries(2, 5)
        self.assertEqual(len(result), 1)
        self.assertNotIn("幽灵", result[0].summary)
        build_index(self.root)
        self.chapter.write_text("后来改过，但没有重新接受。", encoding="utf-8")
        self.assertEqual(manager._get_recent_chapter_summaries(2, 5), [])

    def test_same_chapter_context_cache_expires_after_body_or_memory_changes(self):
        canon.accept_chapter(self.root, self.chapter, "作者")
        manager = LongTermContextManager(self.root)
        first = manager.get_context_for_chapter(2)
        self.assertTrue(first.recent_chapters)
        self.assertIs(manager.get_context_for_chapter(2), first)
        (self.root / "00_memory/world_state.md").write_text("规则: 禁止涉水", encoding="utf-8")
        second = manager.get_context_for_chapter(2)
        self.assertIsNot(second, first)
        self.assertEqual(second.world_state["规则"], "禁止涉水")
        self.chapter.write_text(CLEAN + "未确认变化。", encoding="utf-8")
        self.assertEqual(manager.get_context_for_chapter(2).recent_chapters, [])

    def test_strict_metrics_do_not_reuse_advisory_pass_cache(self):
        first = flow.continue_write(self.args())
        self.assertTrue(first["ok"], first)
        repeat = flow.continue_write(self.args())
        self.assertTrue(repeat["idempotent_hit"], repeat)
        strict = flow.continue_write(self.args("--strict-prose-metrics"))
        self.assertFalse(strict["idempotent_hit"])
        self.assertFalse(strict["ok"])
        self.assertTrue(strict["quality_after"]["strict_prose_metrics"])

    def test_request_key_changes_with_policy_receipt_and_review(self):
        args = self.args()
        def key():
            return flow.make_request_id(args, self.chapter, "核对", flow.file_sha1(self.chapter), self.root)
        original = key()
        (self.root / ".novel_policy.json").write_text('{"pacing":{"enabled":false}}', encoding="utf-8")
        policy = key()
        self.assertNotEqual(original, policy)
        canon.accept_chapter(self.root, self.chapter, "作者")
        accepted = key()
        self.assertNotEqual(policy, accepted)
        review = self.root / "04_editing/gate_artifacts/test/ai_flavor_review.json"
        review.parent.mkdir(parents=True)
        review.write_text("{}", encoding="utf-8")
        self.assertNotEqual(key(), accepted)

    def test_postaccept_index_failure_preserves_consistent_commit(self):
        self.chapter.write_text(HIGH, encoding="utf-8")
        final_body = "只属于最终接受稿的银盏。\n" + CLEAN
        runner = flow.run_python
        def run(script, argv):
            if script.name == "plot_rag_retriever.py" and argv[0] == "build" and canon.acceptance(self.root, self.chapter)[0]:
                return 1, "", "offline failure", {"ok": False}
            return runner(script, argv)
        def polish(*_, **kwargs):
            self.chapter.write_text(final_body, encoding="utf-8")
            return {"ok": True}
        with patch.object(flow, "run_python", side_effect=run), patch.object(writer, "write_chapter", side_effect=polish):
            result = flow.continue_write(self.args("--llm-provider", "offline"))
        self.assertTrue(result["accepted"])
        self.assertTrue(result["postprocess_degraded"])
        self.assertFalse(result["rollback_applied"])
        self.assertTrue(canon.acceptance(self.root, self.chapter)[0])
        self.assertEqual(self.chapter.read_text(encoding="utf-8"), final_body)
        summary = (self.root / "00_memory/chapter_summaries/recent.md").read_text(encoding="utf-8")
        self.assertIn("只属于最终接受稿的银盏", summary)
        self.assertFalse((self.root / ".flow/continue_write_cache.json").exists())
        with self.assertRaises(RuntimeError):
            canon.require_current_index(self.root, "legacy")

    def test_postaccept_exception_preserves_body_and_acceptance(self):
        original = flow.update_flow_metrics
        failed = False
        def metrics(*args, **kwargs):
            nonlocal failed
            if not failed and canon.acceptance(self.root, self.chapter)[0]:
                failed = True
                raise RuntimeError("offline postcommit failure")
            return original(*args, **kwargs)
        with patch.object(flow, "update_flow_metrics", side_effect=metrics):
            result = flow.continue_write(self.args())
        self.assertFalse(result["ok"])
        self.assertTrue(result["accepted"])
        self.assertFalse(result["rollback_applied"])
        self.assertTrue(canon.acceptance(self.root, self.chapter)[0])

    def test_auto_retry_shares_two_polish_calls_and_never_accepts_unresolved_text(self):
        self.chapter.write_text(HIGH, encoding="utf-8")
        configs = []
        def polish(*_, **kwargs):
            configs.append(kwargs["config_overrides"])
            return {"ok": True}
        with patch.object(writer, "write_chapter", side_effect=polish):
            result = flow.continue_write(self.args("--llm-provider", "offline", retry=True))
        self.assertEqual(len(configs), 2, result)
        self.assertEqual(result["humanizer_budget"], {"limit": 2, "used": 2})
        self.assertFalse(result["gate_passed_final"])
        self.assertFalse(canon.accepted_files(self.root)[0])
        self.assertTrue(all(c["skip_humanizer"] and not c["auto_update_memory"] for c in configs))


if __name__ == "__main__":
    unittest.main()
