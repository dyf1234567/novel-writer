from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import style_fewshot


class StyleWriterBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        configured_style_home = os.environ.get("STYLE_WRITER_SKILL_HOME")
        style_home = (
            Path(configured_style_home).expanduser()
            if configured_style_home
            else Path(__file__).resolve().parents[3] / "style-writer"
        )
        if not (style_home / "scripts" / "style_engine.py").is_file():
            self.skipTest("optional style-writer skill is not installed")

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        authors = self.root / "authors"
        pack_dir = authors / "demo"
        pack_dir.mkdir(parents=True)
        pack = {
            "schema_version": 1,
            "slug": "demo",
            "display_name": "demo inspired",
            "positioning": "high-level inspiration only",
            "corpus": {"env": "DEMO_UNUSED_CORPUS"},
            "default_family": "fiction",
            "unmatched_family": "fiction",
            "families": [{"id": "fiction", "label": "小说", "patterns": []}],
            "traits": ["动作承载情绪"],
            "scene_controls": ["克制收束"],
            "negative_constraints": ["不借用原作人物"],
        }
        (pack_dir / "pack.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        corpus = self.root / "corpus"
        corpus.mkdir()
        self.source_phrase = "雨夜里的少年把旧车票折好。他说没关系，手指却一直按着口袋。"
        (corpus / "小说.txt").write_text((self.source_phrase + "\n\n") * 8, encoding="utf-8")
        self.old_env = {key: os.environ.get(key) for key in ("AUTHOR_STYLE_HOME", "STYLE_INDEX_HOME", "STYLE_WRITER_SKILL_HOME", "DEMO_UNUSED_CORPUS")}
        os.environ["AUTHOR_STYLE_HOME"] = str(authors)
        os.environ["STYLE_INDEX_HOME"] = str(self.root / "indexes")
        os.environ["STYLE_WRITER_SKILL_HOME"] = str(style_home)
        os.environ["DEMO_UNUSED_CORPUS"] = str(corpus)

    def tearDown(self) -> None:
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def test_external_engine_static_fallback(self) -> None:
        project = self.root / "project"
        project.mkdir()
        result = style_fewshot.retrieve_fewshot(project, "demo", "雨夜重逢")
        self.assertTrue(result["ok"])
        self.assertEqual(result["engine"], "style-writer")
        self.assertEqual(result["mode"], "static")
        self.assertIn("动作承载情绪", result["text"])
        self.assertIn("不借用原作人物", result["text"])
        self.assertNotIn("【检索证据】", result["text"])

    def test_indexed_pure_style_omits_source_prose(self) -> None:
        engine = style_fewshot._load_style_writer_engine()
        engine.build_index("demo", provider="hash")
        project = self.root / "project"
        project.mkdir()
        result = style_fewshot.retrieve_fewshot(project, "demo", "雨夜 少年 车票")
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "hybrid")
        self.assertFalse(result["source_excerpts"])
        self.assertNotIn(self.source_phrase, result["text"])
        self.assertNotIn("【检索证据】", result["text"])
        self.assertIn("sample_count", result["text"])

    def test_explicit_opt_in_can_include_source_excerpt(self) -> None:
        engine = style_fewshot._load_style_writer_engine()
        engine.build_index("demo", provider="hash")
        project = self.root / "project"
        project.mkdir()
        result = style_fewshot.retrieve_fewshot(
            project, "demo", "雨夜 少年 车票", allow_source_excerpts=True
        )
        self.assertTrue(result["source_excerpts"])
        self.assertIn("【检索证据】", result["text"])
        self.assertIn("雨夜里的少年", result["text"])


if __name__ == "__main__":
    unittest.main()
