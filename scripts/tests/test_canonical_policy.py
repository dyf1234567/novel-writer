"""Acceptance and audit invariants across independent commands."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anti_resolution_guard import AntiResConfig, cmd_check, cmd_constraint
from canonical_state import accept_chapter, acceptance, require_current_index
from creative_checkpoint import decide, evaluate
from local_vector_retriever import build_index as vector_build, query_index as vector_query
from plot_rag_retriever import build_index as legacy_build, fts5_build_index, fts5_retrieve
from project_policy import load_policy
from volume_audit import collect_audit, complete_audit, status as audit_status


def fixture(root: Path, name: str = "第1章-旧约.md", accepted: bool = False) -> Path:
    (root / "03_manuscript").mkdir(exist_ok=True)
    path = root / "03_manuscript" / name
    path.write_text("# 第一章\n\n旧约埋在铜铃下面，主角还不知道。\n" * 8, encoding="utf-8")
    if accepted:
        accept_chapter(root, path, "fixture")
    return path


class CanonicalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_all_three_index_builders_exclude_unaccepted_text(self):
        fixture(self.root)
        legacy = legacy_build(self.root)
        fts = fts5_build_index(self.root)
        vector = vector_build(self.root, provider="hash", model="test")
        self.assertEqual((legacy["chapter_count"], fts["chapter_count"],
                          vector["chapter_count"]), (0, 0, 0))
        self.assertTrue(legacy["acceptance_warnings"])
        for engine in ("legacy", "fts5", "vector"):
            require_current_index(self.root, engine)

    def test_accept_build_modify_invalidates_every_index(self):
        path = fixture(self.root, accepted=True)
        self.assertEqual(legacy_build(self.root)["chapter_count"], 1)
        self.assertEqual(fts5_build_index(self.root)["chapter_count"], 1)
        self.assertEqual(vector_build(self.root, provider="hash", model="test")["chapter_count"], 1)
        self.assertTrue(vector_query(self.root, "铜铃", provider="hash", model="test")["retrieved"])
        path.write_text(path.read_text(encoding="utf-8") + "\n旧约已改。", encoding="utf-8")
        self.assertFalse(acceptance(self.root, path)[0])
        for engine in ("legacy", "fts5", "vector"):
            with self.subTest(engine=engine), self.assertRaisesRegex(RuntimeError, "过期"):
                require_current_index(self.root, engine)
        with self.assertRaisesRegex(RuntimeError, "过期"):
            vector_query(self.root, "铜铃", provider="hash", model="test")
        self.assertEqual(legacy_build(self.root)["chapter_count"], 0)
        accept_chapter(self.root, path, "fixture")
        self.assertEqual(fts5_build_index(self.root)["chapter_count"], 1)
        self.assertTrue(fts5_retrieve(self.root, self.root / "00_memory/retrieval/story_index.sqlite",
                                      "铜铃", 3, 3, 2, 200)["retrieved"])

    def test_stub_duplicate_and_changed_gate_fail_closed(self):
        path = fixture(self.root)
        path.write_text("<!-- NOVEL_DRAFT_STATUS: fallback_template -->\n模板正文", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "模板"):
            accept_chapter(self.root, path, "reviewer")
        path.write_text("正式稿", encoding="utf-8")
        accept_chapter(self.root, path, "reviewer")
        other = fixture(self.root, "第1章-第二份.md")
        with self.assertRaisesRegex(ValueError, "双份"):
            accept_chapter(self.root, other, "reviewer")
        gate_dir = self.root / "04_editing/gate_artifacts/第1章-旧约"
        gate_dir.mkdir(parents=True)
        (gate_dir / "gate_result.json").write_text(json.dumps({"passed": True,
                  "chapter_sha256": "old"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "过期"):
            accept_chapter(self.root, path, "reviewer")

    def test_audit_cannot_approve_blocked_or_stale_evidence(self):
        fixture(self.root, accepted=True)
        blocked = collect_audit(self.root, 1, start=1, end=2)
        self.assertEqual(blocked["state"]["status"], "blocked")
        with self.assertRaisesRegex(RuntimeError, "阻断"):
            complete_audit(self.root, 1, "pass", "reviewer", "核对过")
        fixture(self.root, "第2章-远行.md", accepted=True)
        for name in ("novel_state.md", "character_tracker.md", "timeline.md",
                     "world_state.md", "foreshadowing_tracker.md"):
            path = self.root / "00_memory" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("已核对", encoding="utf-8")
        pending = collect_audit(self.root, 1, start=1, end=2)
        self.assertEqual(pending["state"]["status"], "pending_review")
        complete_audit(self.root, 1, "pass", "reviewer", "已读两章")
        self.assertTrue(audit_status(self.root, 1)["ok"])
        (self.root / "00_memory/timeline.md").write_text("时间线修订", encoding="utf-8")
        self.assertEqual(audit_status(self.root, 1)["state"]["status"], "stale")
        with self.assertRaisesRegex(RuntimeError, "过期"):
            complete_audit(self.root, 1, "pass", "reviewer", "旧证据")

    def test_checkpoint_approval_expires_after_revision(self):
        path = fixture(self.root, accepted=True)
        (self.root / "00_memory").mkdir(exist_ok=True)
        (self.root / "00_memory/outline_anchors.json").write_text("{}", encoding="utf-8")
        self.assertFalse(evaluate(self.root, next_chapter=2, interval=1)["ok"])
        decide(self.root, 1, "approved", "reader", "已经读完")
        self.assertTrue(evaluate(self.root, next_chapter=2, interval=1)["ok"])
        path.write_text(path.read_text(encoding="utf-8") + "新增一段", encoding="utf-8")
        self.assertFalse(evaluate(self.root, next_chapter=2, interval=1)["ok"])

    def test_narrative_policy_is_opt_in_and_finale_keeps_forbidden(self):
        chapter = fixture(self.root)
        chapter.write_text("终于解决。终于解决。\n不许说的秘密。", encoding="utf-8")
        anchors = self.root / "00_memory/outline_anchors.json"
        anchors.parent.mkdir(exist_ok=True)
        anchors.write_text(json.dumps({"current_node": {"forbidden_reveals": ["不许说的秘密"]}}), encoding="utf-8")
        args = SimpleNamespace(project_root=str(self.root), chapter_file=str(chapter), is_finale=False)
        default = cmd_check(args, AntiResConfig())
        self.assertFalse(default["passed"])
        self.assertEqual(len(default["errors"]), 1)
        (self.root / ".novel_policy.json").write_text(json.dumps({
            "narrative": {"avoid_resolution": True, "cliffhanger": True,
                          "finale_chapters": [1]}}), encoding="utf-8")
        finale = cmd_check(args, AntiResConfig())
        self.assertEqual(len(finale["errors"]), 1)
        self.assertTrue(finale["is_finale"])
        planned = cmd_constraint(SimpleNamespace(project_root=str(self.root), chapter=1), AntiResConfig())
        self.assertNotIn("本章不解决核心矛盾", planned["constraint_prompt"])
        self.assertIn("禁止揭露", planned["constraint_prompt"])

    def test_invalid_policy_rejected(self):
        (self.root / ".novel_policy.json").write_text('{"pacing":{"enabled":"yes"}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "布尔"):
            load_policy(self.root)


if __name__ == "__main__":
    unittest.main()
