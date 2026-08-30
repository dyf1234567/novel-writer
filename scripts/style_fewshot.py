#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作者风格启发上下文自动注入 + 人格层提醒（写前自动链路）

把之前「手动 / 由主 Agent 调用」的 style_corpus 检索，接入 /继续写 自动链路：
写每章前自动从目标作者风格库（authors/<slug>/corpus）检索真实样章片段，
注入写作 prompt，让写作模型每章都能读到目标作者的语感参照；
同时检查本项目「人格层」（主角 / 关键角色的声音设定）是否已建立，
未建立时：① 生成填写模板 ② 提醒用户去建立 ③ 写入 persistent 提醒产物。
不自动代填人格层，以免 AI 把被模仿作者的角色口头禅套到自己的主角身上。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from paths import author_style_root

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 人格层待填字段（须与 PERSONA_TEMPLATE 中的标签完全一致）
PERSONA_FIELDS = ["口头禅", "吐槽功能", "紧张时的反应", "OOC 红线"]

PERSONA_TEMPLATE = """# 角色人格层（本项目主角 / 关键角色声音设定）

> 用途：文风复刻时约束「角色声音」，避免 AI 把被模仿作者（如江南）的角色口头禅 / 说话方式
> 套用到你自己的主角身上。写书前请至少填好「主角」一项。
> 本文件由你维护，不会被自动改写。

## 主角
- 口头禅：
- 吐槽功能（吐槽风格、频率、典型句式）：
- 紧张时的反应（口误 / 小动作 / 说话方式变化）：
- OOC 红线（绝对不能让该角色说的话 / 做的事）：

## 主要配角（可选，按需增删）
- 角色A：
  - 口头禅：
  - 吐槽功能：
  - 紧张时反应：
  - OOC 红线：
"""

_PLACEHOLDER_TOKENS = ("待填写", "待填", "（待", "todo", "tbd", "此处", "示例", "（示例")


def _norm(v: object) -> str:
    return (v or "").strip()


def _authors_dir() -> Path:
    return author_style_root()


def _style_writer_engine_path() -> Optional[Path]:
    """Locate the independent style-writer engine without making it mandatory."""
    configured = os.getenv("STYLE_WRITER_SKILL_HOME")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser() / "scripts" / "style_engine.py")
    candidates.append(Path(__file__).resolve().parents[2] / "style-writer" / "scripts" / "style_engine.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_style_writer_engine():
    path = _style_writer_engine_path()
    if path is None:
        return None
    module_name = "novel_writer_external_style_engine"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# 已知作者别名提示（用于 style_anchor.md 缺「风格作者：」标签时，从标题/正文反查）
# 形如「风格锚点 · 江南语言皮肤 × 白狐叙事人格」也能识别为 jiangnan。
_AUTHOR_HINT_DEFAULTS: Dict[str, List[str]] = {
    "jiangnan": ["江南"],
    "fenghuo": ["烽火", "烽火戏诸侯"],
}


def _author_keyword_map() -> Dict[str, List[str]]:
    """slug -> 用于反查的中文关键词列表（默认值 + 各作者 index.json 的 name/aliases）。"""
    amap: Dict[str, List[str]] = {k: list(v) for k, v in _AUTHOR_HINT_DEFAULTS.items()}
    authors_dir = _authors_dir()
    if authors_dir.is_dir():
        for sub in authors_dir.iterdir():
            if not sub.is_dir():
                continue
            slug = sub.name.lower()
            amap.setdefault(slug, [])
            idx = sub / "index.json"
            pack_file = sub / "pack.json"
            if idx.exists() or pack_file.exists():
                try:
                    source = pack_file if pack_file.exists() else idx
                    data = json.loads(source.read_text(encoding="utf-8", errors="ignore"))
                    if isinstance(data, dict):
                        name = data.get("display_name") or data.get("name")
                        if isinstance(name, str):
                            amap[slug].append(name)
                        if isinstance(data.get("aliases"), list):
                            amap[slug].extend(str(a) for a in data["aliases"])
                except Exception:
                    pass
    return amap


def _match_author_hint(text: str) -> Optional[str]:
    """在 style_anchor.md 文本中反查已知作者 slug；未命中返回 None。"""
    t = (text or "").lower()
    for slug, kws in _author_keyword_map().items():
        for kw in kws:
            if kw and kw.lower() in t:
                return slug
    return None


def resolve_style_author(
    project_root: Path, override: Optional[str] = None
) -> Optional[str]:
    """解析本项目要模仿的目标作者风格 slug。

    优先级：命令行 --style-author > 项目配置 style_author > style_anchor.md 标注。
    返回 slug 或 None（无风格模仿时）。
    """
    if override and override.strip():
        return override.strip().lower()
    # 1) 项目配置 .novel_writer_config.yaml
    cfg = project_root / ".novel_writer_config.yaml"
    if cfg.exists():
        try:
            txt = cfg.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"style_author\s*[:=]\s*['\"]?([a-z0-9_-]+)", txt)
            if m:
                return m.group(1)
        except Exception:
            pass
    # 2) style_anchor.md 标注（与配置检查同级，不依赖配置是否存在）
    anchor = project_root / "00_memory" / "style_anchor.md"
    if anchor.exists():
        try:
            txt = anchor.read_text(encoding="utf-8", errors="ignore")
            for label in ("风格作者", "目标作者", "style_author"):
                m = re.search(rf"{label}\s*[：:]\s*['\"]?([a-z0-9_-]+)", txt)
                if m:
                    return m.group(1)
        except Exception:
            pass
    # 3) style_anchor.md 标题/正文反查（兼容「风格锚点 · 江南语言皮肤」但缺标签的情况）
    anchor = project_root / "00_memory" / "style_anchor.md"
    if anchor.exists():
        try:
            txt = anchor.read_text(encoding="utf-8", errors="ignore")
            hint = _match_author_hint(txt)
            if hint:
                return hint
        except Exception:
            pass
    return None


def resolve_style_family(project_root: Path, override: Optional[str] = None) -> Optional[str]:
    """Resolve an optional work family; the author pack default remains the fallback."""
    if override and override.strip():
        return override.strip().lower()
    for candidate in (
        project_root / ".novel_writer_config.yaml",
        project_root / "00_memory" / "style_anchor.md",
    ):
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            match = re.search(
                r"(?:style_family|风格作品族|作品族)\s*[:：=]\s*['\"]?([a-z0-9_-]+)",
                text,
                re.IGNORECASE,
            )
            if match:
                return match.group(1).lower()
        except Exception:
            pass
    return None


def derive_query(chapter_goal: str, scene_hint: str = "") -> str:
    """从章节目标 + 场景暗示构造检索查询。"""
    goal = _norm(chapter_goal)
    if not goal:
        return _norm(scene_hint) or "叙事推进"
    if scene_hint and scene_hint not in goal:
        return f"{goal} {scene_hint}"
    return goal


def retrieve_fewshot(
    project_root: Path,
    author: str,
    query: str,
    top_narrative: int = 2,
    top_dialogue: int = 1,
    family: Optional[str] = None,
    allow_source_excerpts: bool = False,
) -> Dict[str, object]:
    """Prepare author-inspired context, preferring the independent style-writer engine."""
    engine = None
    try:
        engine = _load_style_writer_engine()
    except Exception:
        engine = None
    if engine is not None:
        try:
            prepared = engine.prepare_context(
                author=author,
                query=query,
                family=family,
                limit=max(1, top_narrative + top_dialogue),
                source_lore=False,
                include_excerpts=allow_source_excerpts,
            )
            context = prepared.get("writing_context", {})
            metrics = context.get("retrieval_metrics") or {}
            blocks = [
                "【风格定位】" + str(context.get("positioning", "受高层风格特征启发")),
                "【作品族】" + str((context.get("family") or {}).get("label", "默认")),
                "【高层特征】" + "；".join(str(v) for v in context.get("traits", [])),
                "【场景控制】" + "；".join(str(v) for v in context.get("scene_controls", [])),
                "【检索统计】" + json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                "【禁止项】" + "；".join(str(v) for v in context.get("negative_constraints", [])),
                "【优先级】" + str(context.get("project_priority", "项目设定与人物声音优先")),
            ]
            hits = list(prepared.get("evidence", []))
            if hits and allow_source_excerpts:
                blocks.append("【检索证据】以下短片段仅用于分析节奏，不得续写、拼接或近似改写：")
                for hit in hits:
                    blocks.append(
                        f"（{hit.get('family', '')}｜{hit.get('relpath', '')}）"
                        + str(hit.get("snippet", ""))
                    )
            return {
                "ok": True,
                "author": author,
                "query": query,
                "text": "\n".join(block for block in blocks if block and not block.endswith("】")),
                "hits": hits,
                "mode": prepared.get("mode", "static"),
                "engine": "style-writer",
                "source_excerpts": bool(allow_source_excerpts),
                "note": f"style-writer {prepared.get('mode', 'static')} 模式，证据 {len(hits)} 段",
            }
        except Exception as exc:
            external_error = str(exc)
        else:
            external_error = ""
    else:
        external_error = "style-writer 未安装"

    # The legacy store returns raw prose. Never use it in pure-style mode.
    if not allow_source_excerpts:
        return {
            "ok": False,
            "error": f"style-writer 不可用（{external_error}）；纯风格模式禁止回退到原文样章",
            "author": author,
            "source_excerpts": False,
        }

    # Explicit source-excerpt compatibility fallback for older projects.
    try:
        import style_corpus  # noqa: PLC0415
    except Exception as exc:
        return {"ok": False, "error": f"style_corpus 不可用: {exc}", "author": author}
    try:
        root = _authors_dir()
        idx = root / author / "index.json"
        if not idx.exists():
            return {
                "ok": False,
                "error": f"style-writer 不可用（{external_error}）；旧作者库 [{author}] 也尚未入库",
                "author": author,
            }

        hits: List[Dict[str, object]] = []
        nar = style_corpus.search(root, author, query, top_narrative, kind_filter="narrative")
        if nar.get("ok"):
            hits.extend(nar.get("hits", []))
        dia = style_corpus.search(root, author, query, top_dialogue, kind_filter="dialogue")
        if dia.get("ok"):
            hits.extend(dia.get("hits", []))

        if not hits:
            return {
                "ok": True,
                "author": author,
                "query": query,
                "text": "",
                "hits": [],
                "note": "无命中样章（不影响写作）",
            }

        blocks = []
        for h in hits:
            kind_tag = "语言皮肤-叙事" if h.get("kind") == "narrative" else "角色画像-对话"
            txt = str(h.get("text", "")).strip()
            if txt:
                blocks.append(f"（{kind_tag}｜{h.get('scene', '')}）{txt}")
        text = "\n\n".join(blocks)
        return {
            "ok": True,
            "author": author,
            "query": query,
            "text": text,
            "hits": hits,
            "engine": "legacy-style-corpus",
            "source_excerpts": True,
            "note": f"已回退旧检索器，命中 {len(hits)} 段样章",
        }
    except Exception as exc:
        return {"ok": False, "error": repr(exc)[:200], "author": author}


def check_project_persona(project_root: Path) -> Dict[str, object]:
    """检查本项目人格层是否已建立；缺失时生成模板并给出提醒。"""
    pfile = project_root / "00_memory" / "character_persona.md"
    if not pfile.exists():
        pfile.parent.mkdir(parents=True, exist_ok=True)
        pfile.write_text(PERSONA_TEMPLATE, encoding="utf-8")
        return {
            "established": False,
            "missing": list(PERSONA_FIELDS),
            "path": str(pfile),
            "reason": "人格层文件不存在，已为你生成填写模板",
            "reminder": _reminder_text(pfile, list(PERSONA_FIELDS)),
        }
    txt = pfile.read_text(encoding="utf-8", errors="ignore")
    missing: List[str] = []
    for field in PERSONA_FIELDS:
        # 行锚定（必须以「- 」项目符号开头，避免误匹配正文里出现的字段名，如用途说明中的"口头禅"）；
        # 字段名后允许跟括号批注再遇冒号（如「紧张时的反应（…）：」）；
        # 值只取同行、且排除 \r\n，杜绝 CRLF 下跨行把下一行吞进当前字段值的历史 bug。
        m = re.search(rf"^\s*-\s*{re.escape(field)}[^\n\r]*?[：:][ \t]*([^\n\r]*)", txt, re.MULTILINE)
        if not m:
            missing.append(field)
            continue
        val = _norm(m.group(1))
        if not val or any(tok in val.lower() for tok in _PLACEHOLDER_TOKENS):
            missing.append(field)
    if missing:
        # Older projects may keep the complete persona layer in style_anchor.md.
        # Accept that source instead of forcing a duplicate file.
        anchor = project_root / "00_memory" / "style_anchor.md"
        if anchor.exists():
            anchor_text = anchor.read_text(encoding="utf-8", errors="ignore")
            searchable_anchor = anchor_text.replace("*", "").replace("`", "")
            anchor_labels = (
                r"口头禅\s*[：:]",
                r"吐槽功能[^\n\r]*[：:]",
                r"紧张时的反应[^\n\r]*[：:]",
                r"OOC\s*红线[^\n\r]*[：:]",
            )
            if "叙事人格层" in searchable_anchor and all(
                re.search(pattern, searchable_anchor, re.IGNORECASE) for pattern in anchor_labels
            ):
                return {
                    "established": True,
                    "missing": [],
                    "path": str(anchor),
                    "reason": "人格层已在 style_anchor.md 建立",
                    "reminder": "",
                    "source": "style_anchor",
                }
        return {
            "established": False,
            "missing": missing,
            "path": str(pfile),
            "reason": "以下人格字段尚未填写：" + "、".join(missing),
            "reminder": _reminder_text(pfile, missing),
        }
    return {
        "established": True,
        "missing": [],
        "path": str(pfile),
        "reason": "人格层已建立",
        "reminder": "",
    }


def _reminder_text(pfile: Path, missing: List[str]) -> str:
    return (
        "⚠️ 人格层尚未建立：你正在使用作者风格启发写作，但本项目角色的「声音」还没设定\n"
        f"  → 待填字段：{', '.join(missing)}\n"
        f"  → 请编辑：{pfile}\n"
        "  （不自动代填，以免 AI 把被模仿作者的角色口头禅套到你的主角身上）"
    )


def build_style_injection(
    project_root: Path,
    chapter_goal: str,
    scene_hint: str = "",
    author_override: Optional[str] = None,
    family_override: Optional[str] = None,
    allow_source_excerpts: bool = False,
    enabled: bool = True,
) -> Dict[str, object]:
    """编排：解析风格作者 → 检索 few-shot → 检查人格层。

    返回可注入 prompt 的 fewshot_text 与人格层状态。
    """
    author = resolve_style_author(project_root, author_override) if enabled else None
    family = resolve_style_family(project_root, family_override) if enabled else None
    result: Dict[str, object] = {
        "enabled": enabled,
        "author": author,
        "family": family,
        "fewshot_text": "",
        "fewshot_hits": 0,
        "persona": check_project_persona(project_root),
        "note": "",
    }
    if not enabled:
        result["note"] = "作者风格启发自动注入已关闭"
        return result
    if not author:
        result["note"] = (
            "未配置目标作者风格（在 .novel_writer_config.yaml 设 style_author "
            "或 --style-author 启用）"
        )
        return result

    query = derive_query(chapter_goal, scene_hint)
    fs = retrieve_fewshot(
        project_root,
        author,
        query,
        family=family,
        allow_source_excerpts=allow_source_excerpts,
    )
    result["fewshot_status"] = fs
    if fs.get("ok") and fs.get("text"):
        result["fewshot_text"] = fs["text"]
        result["fewshot_hits"] = len(fs.get("hits", []))
        result["note"] = (
            f"已为作者包 [{author}] 准备纯风格上下文，检索校准 {result['fewshot_hits']} 段"
        )
    elif not fs.get("ok"):
        result["note"] = f"样章检索失败（{fs.get('error', '')}），写作不受影响"
    else:
        result["note"] = f"作者 [{author}] 无命中样章，写作不受影响"
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="作者风格启发上下文自动注入 / 人格层检查")
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--chapter-goal", default="推进下一章剧情")
    ap.add_argument("--scene-hint", default="")
    ap.add_argument("--style-author", default=None)
    ap.add_argument("--style-family", default=None)
    ap.add_argument(
        "--allow-source-excerpts",
        action="store_true",
        help="显式允许把短原文证据放入写作上下文；默认关闭",
    )
    ap.add_argument("--no-style-fewshot", dest="enabled", action="store_false")
    args = ap.parse_args()

    out = build_style_injection(
        Path(args.project_root).expanduser().resolve(),
        args.chapter_goal,
        args.scene_hint,
        author_override=args.style_author,
        family_override=args.style_family,
        allow_source_excerpts=args.allow_source_excerpts,
        enabled=args.enabled,
    )
    print("=" * 60)
    print(f"enabled={out['enabled']}  author={out['author']}")
    print(f"note: {out['note']}")
    p = out.get("persona") or {}
    print(f"persona.established={p.get('established')}  missing={p.get('missing')}")
    if p.get("reminder"):
        print("\n" + p["reminder"])
    if out.get("fewshot_text"):
        print("\n--- 风格启发上下文 ---")
        print(out["fewshot_text"][:1200])
    print("=" * 60)
