#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风格审计（文风复刻增强层 · 审计层）

用作者档案 profile.json 里的判定区间，对成文做 FAIL/WARN 两级判定。
设计移植自 jiangnan-writer/scripts/audit_style.py，但 PROFILES 改为从
profile.json 动态加载 —— 因此任意作者都能审计，不限于预设的江南/烽火。

- FAIL：硬性项，违反即风格穿帮（对话动词体系错用、破折号超限、黑名单词命中）
- WARN：节奏项，偏离语料区间（标点密度、句长、段落节奏）

用法:
    python style_audit.py --author jiangnan --file 章节.md
    python style_audit.py --author jiangnan --dir 03_manuscript/

退出码: 有 FAIL 时为 1，否则 0。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from paths import author_style_root

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_SPLIT = re.compile(r"[。！？…]+")
DAO_RE = re.compile(rf"[一-鿿]{{0,4}}道[：:，,]?\s*[“\"「]")
SHUO_RE = re.compile(rf"[一-鿿]{{1,3}}地?说[：:，,]?\s*[“\"「]")
METAPHOR_RE = re.compile(r"像是|仿佛|似的|像|好像|如同|宛如")
EMDASH_RE = re.compile(r"(?<!—)——(?!—)")
BUSHI_RE = re.compile(r"""不是[^，。！？、；：“”‘’'"「」\n]{1,20}[，,]\s*而?是""")
QUOTE_RE = re.compile(r"[“「\"][^”」\"']{1,500}[”」\"']|[“「\"][^”」\"']{1,500}$")

MIN_RELIABLE_CHARS = 1500


def default_authors_dir() -> Path:
    return author_style_root()


def _slug(author: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", author.lower()).strip("-") or "default"


def _load_profile(authors_root: Path, author: str) -> Dict[str, object]:
    p = authors_root / _slug(author) / "profile.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_layer(authors_root: Path, author: str, layer: str) -> Dict[str, object]:
    """加载分离档案：skin.json（语言皮肤）或 voice.json（角色画像）。"""
    fname = f"{layer}.json"
    p = authors_root / _slug(author) / fname
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def metrics(text: str) -> Dict[str, object]:
    n = len(CJK_RE.findall(text)) or 1
    per_wan = lambda c: round(c / n * 10000, 1)
    sents = [s for s in SENT_SPLIT.split(text) if 2 < len(CJK_RE.findall(s.strip())) < 500]
    slens = sorted(len(CJK_RE.findall(s.strip())) for s in sents) or [0]
    paras = [p.strip() for p in text.splitlines() if len(CJK_RE.findall(p.strip())) > 1]
    plens = sorted(len(CJK_RE.findall(p)) for p in paras) or [0]
    ultra = sum(1 for x in plens if x <= 15)
    dialogue_chars = sum(len(CJK_RE.findall(m.group())) for m in QUOTE_RE.finditer(text))
    return {
        "chars": n,
        "exclaim_per_wan": per_wan(text.count("！")),
        "question_per_wan": per_wan(text.count("？")),
        "ellipsis_per_wan": per_wan(text.count("……")),
        "metaphor_per_wan": per_wan(len(METAPHOR_RE.findall(text))),
        "emdash_per_wan": per_wan(len(EMDASH_RE.findall(text))),
        "bushi_count": len(BUSHI_RE.findall(text)),
        "avg_sentence_chars": round(sum(slens) / len(slens), 1),
        "para_median": plens[len(plens) // 2],
        "ultrashort_pct": round(ultra / len(plens) * 100, 1) if paras else 0.0,
        "dialogue_pct": round(dialogue_chars / n * 100, 1),
        "dao_hits": DAO_RE.findall(text),
        "shuo_hits": SHUO_RE.findall(text),
    }


def strip_afterword(text: str) -> str:
    for mark in ("**作者的话", "作者的话：", "作者的话:"):
        idx = text.find(mark)
        if idx > 0:
            return text[:idx]
    return text


def judge_full(profile: Dict[str, object], m: Dict[str, object], text: str) -> Tuple[List[str], List[str]]:
    fails: List[str] = []
    warns: List[str] = []
    rules = profile.get("rules", {})
    bands = profile.get("bands", {})
    met = profile.get("metrics", {})

    # --- FAIL: 对话动词体系 ---
    verb_sys = rules.get("dialogue_verb_system", "mixed")
    if verb_sys == "shuo" and m["dao_hits"]:
        uniq = sorted(set(m["dao_hits"]))[:8]
        fails.append(f"对话动词用了'道'系 {len(m['dao_hits'])} 处，但语料是'说'系（穿帮）: {uniq}")
    elif verb_sys == "dao" and m["shuo_hits"]:
        uniq = sorted(set(m["shuo_hits"]))[:8]
        fails.append(f"对话动词用了'说'系 {len(m['shuo_hits'])} 处，但语料是'道'系（穿帮）: {uniq}")
    elif verb_sys == "mixed" and m["dao_hits"] and m["shuo_hits"]:
        # 混合体系：两种都允许，但混用超过语料比例时提示
        warns.append("对话动词体系为混合，本段同时出现'道'与'说'——注意与语料的 dao/shuo 比例保持一致")

    # --- FAIL: 黑名单词 ---
    blacklist = rules.get("ai_vocab_blacklist", [])
    black_hits = {w: text.count(w) for w in blacklist if w in text}
    if black_hits:
        fails.append(f"AI 味黑名单命中: {black_hits}")

    # --- FAIL: 破折号超限 ---
    emdash_hi = bands.get("emdash_per_wan", (0, 25))[1]
    if m["emdash_per_wan"] > emdash_hi:
        fails.append(f"句内破折号 {m['emdash_per_wan']}/万字 超上限 {emdash_hi}（AI 高频特征，改回句号/逗号）")

    # --- FAIL: AI 对仗句式 ---
    bushi_max = rules.get("bushi_max", 1)
    if m["bushi_count"] > bushi_max:
        fails.append(f"'不是X而是Y'句式 {m['bushi_count']} 处（上限 {bushi_max}，AI 最爱的对仗结构）")

    reliable = m["chars"] >= MIN_RELIABLE_CHARS
    tag = "" if reliable else "（文本过短，仅供参考）"

    def band(key: str, label: str, val: float) -> None:
        if key not in bands:
            return
        lo, hi = bands[key]
        ref = met.get(key)
        if lo is not None and val < lo:
            warns.append(f"{label}={val} 偏低（语料≈{ref}，建议≥{lo}）{tag}")
        elif hi is not None and val > hi:
            warns.append(f"{label}={val} 偏高（语料≈{ref}，建议≤{hi}）{tag}")

    band("exclaim_per_wan", "感叹号/万字", m["exclaim_per_wan"])
    band("question_per_wan", "问号/万字", m["question_per_wan"])
    band("ellipsis_per_wan", "省略号/万字", m["ellipsis_per_wan"])
    band("metaphor_per_wan", "比喻标记/万字", m["metaphor_per_wan"])
    band("avg_sentence_chars", "平均句长", m["avg_sentence_chars"])
    band("para_median", "段落中位", m["para_median"])
    band("ultrashort_pct", "超短段占比%", m["ultrashort_pct"])

    return fails, warns


def judge_voice(voice: Dict[str, object], m: Dict[str, object], text: str) -> Tuple[List[str], List[str]]:
    """角色画像层审计：对话动词体系 + 人工红线。"""
    fails: List[str] = []
    warns: List[str] = []
    vmet = voice.get("metrics", {})
    persona = voice.get("persona", {})
    dao_n = vmet.get("dao_count", 0)
    shuo_n = vmet.get("shuo_count", 0)

    # --- 对话动词体系 ---
    if dao_n > 0 and shuo_n == 0:
        verb_sys = "dao"
    elif shuo_n > 0 and dao_n == 0:
        verb_sys = "shuo"
    else:
        verb_sys = "mixed"

    if verb_sys == "shuo" and m["dao_hits"]:
        fails.append(f"对话动词用了'道'系 {len(m['dao_hits'])} 处，但角色画像为'说'系（穿帮）: "
                     f"{sorted(set(m['dao_hits']))[:6]}")
    elif verb_sys == "dao" and m["shuo_hits"]:
        fails.append(f"对话动词用了'说'系 {len(m['shuo_hits'])} 处，但角色画像为'道'系（穿帮）: "
                     f"{sorted(set(m['shuo_hits']))[:6]}")

    # --- 人工红线（persona.OOC红线）---
    redlines = persona.get("OOC红线") or []
    if isinstance(redlines, str):
        redlines = [redlines]
    for r in redlines:
        if r and r in text:
            fails.append(f"命中角色 OOC 红线: 「{r}」")

    # --- 人格层未填写提醒 ---
    filled = [k for k, v in persona.items() if isinstance(v, str) and v.strip()]
    if len(filled) < 2:
        warns.append("voice.md 人格层尚未人工填写完整（口头禅/吐槽功能/紧张反应/OOC红线）——"
                     "请项目作者审核填写，否则无法做人格层判定")

    return fails, warns


def audit_file(profile: Dict[str, object], path: Path) -> Tuple[bool, Dict[str, object]]:
    text = strip_afterword(path.read_text(encoding="utf-8", errors="ignore"))
    m = metrics(text)
    fails, warns = judge_full(profile, m, text)
    return (not fails), {"metrics": m, "fails": fails, "warns": warns}


def main() -> int:
    parser = argparse.ArgumentParser(description="风格审计（FAIL/WARN 判定）")
    parser.add_argument("--author", required=True, help="作者标识")
    parser.add_argument("--file", help="待审计文件")
    parser.add_argument("--dir", help="待审计目录（递归所有 .md）")
    parser.add_argument("--layer", default="skin", choices=["skin", "voice", "full"],
                        help="审计层：skin=语言皮肤指标 / voice=角色人格画像 / full=两者都要")
    parser.add_argument("--authors-root", default=str(default_authors_dir()))
    args = parser.parse_args()

    root = Path(args.authors_root).expanduser().resolve()

    # 按层加载档案
    skin = _load_layer(root, args.author, "skin") if args.layer in ("skin", "full") else {}
    voice = _load_layer(root, args.author, "voice") if args.layer in ("voice", "full") else {}
    profile = _load_profile(root, args.author) if args.layer == "full" else {}

    if args.layer == "skin" and not skin:
        print(f"作者 [{args.author}] 无 skin.json，先运行 style_profile.py build-skin")
        return 2
    if args.layer == "voice" and not voice:
        print(f"作者 [{args.author}] 无 voice.json，先运行 style_profile.py build-voice")
        return 2

    targets: List[Path] = []
    if args.file:
        targets.append(Path(args.file).expanduser().resolve())
    elif args.dir:
        targets = sorted(Path(args.dir).expanduser().resolve().rglob("*.md"))
    else:
        print("需要 --file 或 --dir")
        return 2

    any_fail = False
    for t in targets:
        if not t.exists():
            print(f"文件不存在: {t}")
            any_fail = True
            continue
        ok, res = audit_file(profile if args.layer == "full" else (skin if args.layer == "skin" else voice), t)
        if args.layer == "voice":
            # 人格层额外跑 voice 判定
            vf, vw = judge_voice(voice, res["metrics"], strip_afterword(
                t.read_text(encoding="utf-8", errors="ignore")))
            res["fails"].extend(vf)
            res["warns"].extend(vw)
            ok = ok and not vf
        m = res["metrics"]
        layer_tag = {"skin": "语言皮肤", "voice": "角色画像", "full": "综合"}[args.layer]
        print(f"\n== {t} ==  ({m['chars']}字) [{layer_tag}层]")
        print(f"  感叹号{m['exclaim_per_wan']}/万 问号{m['question_per_wan']}/万 省略号{m['ellipsis_per_wan']}/万 "
              f"句长均值{m['avg_sentence_chars']} 段落中位{m['para_median']} 超短段{m['ultrashort_pct']}% "
              f"破折号{m['emdash_per_wan']}/万 比喻{m['metaphor_per_wan']}/万")
        for f_ in res["fails"]:
            print(f"  [FAIL] {f_}")
        for w in res["warns"]:
            print(f"  [WARN] {w}")
        if not res["fails"] and not res["warns"]:
            print("  [PASS] 全部指标在语料区间内")
        any_fail = any_fail or not ok

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
