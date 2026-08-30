#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_fewshot 回归测试：文风复刻 few-shot 自动注入 + 人格层提醒。

可直接运行（python test_style_fewshot.py）或在 pytest 下运行。
"""
import os
import json
import sys
import tempfile
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import style_fewshot as style_mod  # noqa: E402


def _make_project() -> Path:
    root = Path(tempfile.mkdtemp(prefix="sfs_test_"))
    (root / "00_memory").mkdir(parents=True)
    (root / "03_manuscript").mkdir(parents=True)
    return root


def _make_external_pack(root: Path) -> Path:
    authors = root / "authors"
    pack_dir = authors / "demo"
    pack_dir.mkdir(parents=True)
    pack = {
        "schema_version": 1,
        "slug": "demo",
        "display_name": "demo inspired",
        "positioning": "high-level inspiration only",
        "corpus": {"env": "DEMO_UNUSED_CORPUS"},
        "default_family": "fiction",
        "families": [{"id": "fiction", "label": "小说", "patterns": []}],
        "traits": ["动作承载情绪"],
        "scene_controls": ["克制收束"],
        "negative_constraints": ["不借用原作人物"],
    }
    (pack_dir / "pack.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    return authors


class _StyleEnv:
    def __init__(self, root: Path):
        self.values = {key: os.environ.get(key) for key in ("AUTHOR_STYLE_HOME", "STYLE_INDEX_HOME", "STYLE_WRITER_SKILL_HOME")}
        os.environ["AUTHOR_STYLE_HOME"] = str(_make_external_pack(root))
        os.environ["STYLE_INDEX_HOME"] = str(root / "indexes")
        os.environ["STYLE_WRITER_SKILL_HOME"] = str(Path(__file__).resolve().parents[3] / "style-writer")

    def close(self):
        for key, value in self.values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_resolve_style_author_from_config():
    root = _make_project()
    try:
        (root / ".novel_writer_config.yaml").write_text(
            "style_author: jiangnan\n", encoding="utf-8"
        )
        assert style_mod.resolve_style_author(root) == "jiangnan"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_resolve_style_author_from_anchor():
    root = _make_project()
    try:
        (root / "00_memory" / "style_anchor.md").write_text(
            "# 风格锚点\n风格作者：fenghuo\n", encoding="utf-8"
        )
        assert style_mod.resolve_style_author(root) == "fenghuo"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_resolve_style_author_override_wins():
    root = _make_project()
    try:
        (root / ".novel_writer_config.yaml").write_text(
            "style_author: jiangnan\n", encoding="utf-8"
        )
        assert style_mod.resolve_style_author(root, "fenghuo") == "fenghuo"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_resolve_style_family_from_config_and_override():
    root = _make_project()
    try:
        (root / ".novel_writer_config.yaml").write_text(
            "style_author: jiangnan\nstyle_family: jiuzhou\n", encoding="utf-8"
        )
        assert style_mod.resolve_style_family(root) == "jiuzhou"
        assert style_mod.resolve_style_family(root, "longzu") == "longzu"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_retrieve_fewshot_returns_real_prose():
    root = _make_project()
    env = _StyleEnv(root)
    try:
        out = style_mod.retrieve_fewshot(
            root, "demo", "雨夜 相遇", top_narrative=2, top_dialogue=1
        )
        assert out["ok"] is True, out.get("error")
        assert out["text"], "应生成风格启发上下文"
        assert "动作承载情绪" in out["text"]
        assert out["engine"] == "style-writer"
    finally:
        env.close()
        shutil.rmtree(root, ignore_errors=True)


def test_check_project_persona_creates_template_then_established():
    root = _make_project()
    try:
        # 第一次：文件不存在 → 生成模板 + established=False
        p1 = style_mod.check_project_persona(root)
        assert p1["established"] is False
        assert (root / "00_memory" / "character_persona.md").exists()
        assert p1["missing"], "应有缺失字段提醒"

        # 填写主角字段后 → established=True
        filled = p1["reminder"]  # noqa: F841
        tpl = (root / "00_memory" / "character_persona.md").read_text(encoding="utf-8")
        tpl = tpl.replace("- 口头禅：", "- 口头禅：喂，你这人怎么回事")
        tpl = tpl.replace("- 吐槽功能（吐槽风格、频率、典型句式）：",
                          "- 吐槽功能（吐槽风格、频率、典型句式）：每句结尾带一句毒舌")
        tpl = tpl.replace("- 紧张时的反应（口误 / 小动作 / 说话方式变化）：",
                          "- 紧张时的反应：会不自觉地搓手指")
        tpl = tpl.replace("- OOC 红线（绝对不能让该角色说的话 / 做的事）：",
                          "- OOC 红线：绝不主动出卖朋友")
        (root / "00_memory" / "character_persona.md").write_text(tpl, encoding="utf-8")
        p2 = style_mod.check_project_persona(root)
        assert p2["established"] is True, p2
        assert p2["missing"] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_project_persona_accepts_style_anchor_layer():
    root = _make_project()
    try:
        (root / "00_memory" / "character_persona.md").write_text(
            style_mod.PERSONA_TEMPLATE, encoding="utf-8"
        )
        (root / "00_memory" / "style_anchor.md").write_text(
            """# 风格锚点
## 叙事人格层
- 口头禅：先算账
- 吐槽功能：用算计消解恐惧
- 紧张时的反应：手指敲桌
- **OOC红线（禁止）**：不背叛朋友
""",
            encoding="utf-8",
        )
        result = style_mod.check_project_persona(root)
        assert result["established"] is True, result
        assert result["source"] == "style_anchor"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_style_injection_disabled():
    root = _make_project()
    try:
        out = style_mod.build_style_injection(root, "推进剧情", enabled=False)
        assert out["enabled"] is False
        assert out["fewshot_text"] == ""
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_style_injection_no_author():
    root = _make_project()
    try:
        out = style_mod.build_style_injection(root, "推进剧情", enabled=True)
        assert out["author"] is None
        assert out["persona"]["established"] is False  # 人格层提醒仍触发
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_style_injection_full():
    root = _make_project()
    env = _StyleEnv(root)
    try:
        out = style_mod.build_style_injection(
            root, "人物在雨夜相遇", author_override="demo", enabled=True
        )
        assert out["author"] == "demo"
        assert out["fewshot_text"], "应注入风格上下文"
        assert out["persona"]["established"] is False  # 模板刚生成，未填
        assert out["persona"]["reminder"]
    finally:
        env.close()
        shutil.rmtree(root, ignore_errors=True)


def _main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _main()
