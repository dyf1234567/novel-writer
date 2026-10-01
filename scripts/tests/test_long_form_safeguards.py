import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from creative_checkpoint import decide, evaluate
from canonical_state import accept_chapter
from local_vector_retriever import build_index, query_index
from plot_rag_retriever import _rrf_hybrid
from volume_audit import collect_audit, complete_audit


def make_project(root: Path, chapter_count: int = 2, volume_end: int = 2) -> None:
    (root / "03_manuscript").mkdir(parents=True)
    (root / "00_memory").mkdir(parents=True)
    for number in range(1, chapter_count + 1):
        topic = "铜铃密约" if number == 1 else "雪山归途"
        (root / "03_manuscript" / f"第{number}章-测试.md").write_text(
            f"# 第{number}章 测试\n\n{topic}。这是已接受的章节正文，人物做出了不可逆的选择。\n",
            encoding="utf-8",
        )
        accept_chapter(root, root / "03_manuscript" / f"第{number}章-测试.md", "fixture")
    for name in (
        "novel_state.md",
        "character_tracker.md",
        "timeline.md",
        "world_state.md",
        "foreshadowing_tracker.md",
    ):
        (root / "00_memory" / name).write_text(f"# {name}\n", encoding="utf-8")
    anchors = {
        "volumes": [
            {"volume": 1, "title": "第一卷", "chapter_range": [1, volume_end]}
        ]
    }
    (root / "00_memory" / "outline_anchors.json").write_text(
        json.dumps(anchors, ensure_ascii=False), encoding="utf-8"
    )


class TestLocalVectorRetriever(unittest.TestCase):
    def test_hash_provider_builds_and_queries_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            built = build_index(root, provider="hash", model="test-hash", incremental=False)
            self.assertTrue(built["ok"])
            self.assertEqual(built["chapter_count"], 2)
            self.assertFalse(built["semantic"])
            result = query_index(root, "铜铃密约", provider="hash", model="test-hash")
            self.assertTrue(result["ok"])
            self.assertEqual(result["retrieved"][0]["chapter_no"], 1)

    def test_hybrid_fusion_preserves_renderable_fields(self):
        lexical = {
            "query": "旧约",
            "query_entities": [],
            "retrieved": [
                {
                    "chapter_file": "第1章-测试.md",
                    "chapter_no": 1,
                    "score": 2.0,
                    "reason": {"token_overlap": 1},
                    "summary": "摘要",
                    "events": [],
                    "locations": [],
                    "foreshadow_refs": [],
                    "passages": [{"text": "旧约片段", "reason": "fts5", "score": 2.0}],
                }
            ],
            "relation_snippets": [],
        }
        vector = {
            "query": "旧约",
            "retrieved": [
                {"chapter_file": "第1章-测试.md", "chapter_no": 1, "text": "语义片段", "score": 0.9}
            ],
        }
        result = _rrf_hybrid(lexical, vector, 4)
        row = result["retrieved"][0]
        for key in ("reason", "summary", "events", "locations", "foreshadow_refs", "passages"):
            self.assertIn(key, row)
        self.assertEqual(row["sources"], ["fts5", "vector"])

    def test_hybrid_fusion_promotes_unusually_strong_direct_lexical_evidence(self):
        lexical = {
            "query": "谁放下权力后不再替别人决定",
            "query_entities": [],
            "retrieved": [
                {
                    "chapter_file": "第4章-背景.md",
                    "chapter_no": 4,
                    "score": 2.0,
                    "passages": [{"text": "规则反噬的背景", "score": 2.0}],
                },
                {
                    "chapter_file": "第11章-答案.md",
                    "chapter_no": 11,
                    "score": 12.0,
                    "passages": [{"text": "它不再替别人决定", "score": 12.0}],
                },
            ],
            "relation_snippets": [],
        }
        vector = {
            "query": lexical["query"],
            "retrieved": [
                {"chapter_file": "第4章-背景.md", "chapter_no": 4, "text": "背景", "score": 0.8},
                {"chapter_file": "第11章-答案.md", "chapter_no": 11, "text": "答案", "score": 0.79},
            ],
        }

        result = _rrf_hybrid(lexical, vector, 2)

        self.assertEqual(result["retrieved"][0]["chapter_file"], "第11章-答案.md")
        self.assertGreater(
            result["retrieved"][0]["fusion"]["lexical_evidence_bonus"],
            result["retrieved"][1]["fusion"]["lexical_evidence_bonus"],
        )
        self.assertTrue(result["retrieval_stats"]["direct_lexical_evidence_bonus"])

    def test_hybrid_fusion_counts_each_vector_chapter_once(self):
        lexical = {"query": "测试", "query_entities": [], "retrieved": [], "relation_snippets": []}
        vector = {
            "query": "测试",
            "retrieved": [
                {"chapter_file": "第1章.md", "chapter_no": 1, "text": "片段一", "score": 0.9},
                {"chapter_file": "第1章.md", "chapter_no": 1, "text": "片段二", "score": 0.8},
                {"chapter_file": "第2章.md", "chapter_no": 2, "text": "片段三", "score": 0.7},
            ],
        }

        result = _rrf_hybrid(lexical, vector, 2)
        first = result["retrieved"][0]

        self.assertEqual(first["chapter_file"], "第1章.md")
        self.assertAlmostEqual(first["fusion"]["rrf_score"], 1.0 / 61, places=6)
        self.assertEqual(len(first["passages"]), 2)
        self.assertEqual(result["retrieval_stats"]["vector_chapters_fused"], 2)

    def test_hybrid_fusion_reserves_semantic_only_slot_in_broader_results(self):
        lexical = {
            "query": "同义改写",
            "query_entities": [],
            "retrieved": [
                {"chapter_file": "第1章.md", "chapter_no": 1, "score": 3.0, "passages": []},
                {"chapter_file": "第2章.md", "chapter_no": 2, "score": 2.0, "passages": []},
                {"chapter_file": "第3章.md", "chapter_no": 3, "score": 1.0, "passages": []},
            ],
            "relation_snippets": [],
        }
        vector = {
            "query": "同义改写",
            "retrieved": [
                {"chapter_file": "第1章.md", "chapter_no": 1, "text": "共同命中", "score": 0.9},
                {"chapter_file": "第2章.md", "chapter_no": 2, "text": "共同命中", "score": 0.8},
                {"chapter_file": "第4章.md", "chapter_no": 4, "text": "纯语义命中", "score": 0.7},
            ],
        }

        result = _rrf_hybrid(lexical, vector, 3)

        self.assertIn("第4章.md", [row["chapter_file"] for row in result["retrieved"]])
        self.assertTrue(result["retrieval_stats"]["semantic_only_slot_reserved"])


class TestVolumeAudit(unittest.TestCase):
    def test_collection_is_not_automatic_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            payload = collect_audit(root, 1)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["state"]["status"], "pending_review")
            completed = complete_audit(root, 1, "pass", "tester", "已核对正稿")
            self.assertTrue(completed["ok"])
            self.assertEqual(completed["state"]["status"], "pass")


class TestCreativeCheckpoint(unittest.TestCase):
    def test_interval_checkpoint_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root, chapter_count=10, volume_end=20)
            pending = evaluate(root, next_chapter=11, interval=10)
            self.assertTrue(pending["due"])
            self.assertFalse(pending["ok"])
            decide(root, completed_chapter=10, status="approved", reviewer="tester", notes="继续")
            approved = evaluate(root, next_chapter=11, interval=10)
            self.assertTrue(approved["ok"])

    def test_volume_boundary_requires_passed_audit_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root, chapter_count=2, volume_end=2)
            pending = evaluate(root, next_chapter=3, interval=10, require_volume_audit=True)
            self.assertFalse(pending["ok"])
            self.assertEqual(pending["volume_audit_status"], "pending_review")
            decide(root, completed_chapter=2, status="approved", reviewer="tester", notes="卷末通过")
            still_pending = evaluate(root, next_chapter=3, interval=10, require_volume_audit=True)
            self.assertFalse(still_pending["ok"])
            complete_audit(root, 1, "pass", "tester", "全卷连续性通过")
            approved = evaluate(root, next_chapter=3, interval=10, require_volume_audit=True)
            self.assertTrue(approved["ok"])


if __name__ == "__main__":
    unittest.main()
