#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风格档案生成器（文风复刻增强层 · 规则层）

从已入库的作者语料计算量化指标，生成两份产物：
1) profile.json —— 含审计判定区间的结构化指标（供 style_audit.py 使用）
2) rules.md    —— 人类可读的写作规则 + 禁区清单（供 LLM 写作时加载）

用法:
    python style_profile.py build --author jiangnan
    python style_profile.py show  --author jiangnan

指标设计参考 jiangnan-writer/scripts/audit_style.py：
- 硬性项(FAIL)：对话动词体系（道/说）、破折号密度、AI 高频句式
- 节奏项(WARN)：感叹号/问号/省略号/比喻密度、平均句长、段落中位、超短段占比

纯标准库实现。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from paths import author_style_root

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_SPLIT = re.compile(r"[。！？…]+")


def _cjk_len(text: str) -> int:
    return len(CJK_RE.findall(text))
DAO_RE = re.compile(rf"[一-鿿]{{0,4}}道[：:，,]?\s*[“\"「]")
SHUO_RE = re.compile(rf"[一-鿿]{{1,3}}地?说[：:，,]?\s*[“\"「]")
METAPHOR_RE = re.compile(r"像是|仿佛|似的|像|好像|如同|宛如")
EMDASH_RE = re.compile(r"(?<!—)——(?!—)")
BUSHI_RE = re.compile(r"""不是[^，。！？、；：“”‘’'"「」\n]{1,20}[，,]\s*而?是""")
QUOTE_RE = re.compile(r"[“「\"][^”」\"']{1,500}[”」\"']|[“「\"][^”」\"']{1,500}$")

AI_VOCAB = [
    "不禁", "仿佛", "映入眼帘", "心中暗道", "不由得", "宛如", "愈发", "淡然",
    "整个世界", "一抹", "一丝", "低垂", "深邃", "缓缓", "轻轻", "微微", "嘴角",
]

STOP_PHRASES = {
    "我们", "你们", "他们", "她们", "它们", "这个", "那个", "一种", "没有", "已经",
    "因为", "所以", "如果", "但是", "然后", "自己", "不是", "不会", "就是", "还是",
    "一个", "一些", "可以", "时候", "什么", "怎么", "这样", "那样", "起来", "进去",
}


def default_authors_dir() -> Path:
    return author_style_root()


def _slug(author: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", author.lower()).strip("-") or "default"


def _load_entries(authors_root: Path, author: str) -> List[Dict[str, object]]:
    a_dir = authors_root / _slug(author)
    index_path = a_dir / "index.json"
    if not index_path.exists():
        return []
    return json.loads(index_path.read_text(encoding="utf-8")).get("entries", [])


def _compute(text: str) -> Dict[str, object]:
    """从合并语料计算全部指标。"""
    n = _cjk_len(text) or 1
    per_wan = lambda c: round(c / n * 10000, 1)

    sents = [s for s in SENT_SPLIT.split(text) if 2 < _cjk_len(s.strip()) < 500]
    slens = sorted(_cjk_len(s.strip()) for s in sents) or [0]

    paras = [p.strip() for p in text.splitlines() if _cjk_len(p.strip()) > 1]
    plens = sorted(_cjk_len(p) for p in paras) or [0]
    ultra = sum(1 for x in plens if x <= 15)
    med = plens[len(plens) // 2]

    dialogue_chars = sum(_cjk_len(m.group()) for m in QUOTE_RE.finditer(text))
    dialogue_ratio = round(dialogue_chars / n, 4)

    first_p = sum(1 for w in ("我", "我们") if w in text)
    third_p = sum(1 for w in ("他", "她", "他们") if w in text)

    sequences = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    counter: Counter = Counter()
    for seq in sequences:
        seq_len = len(seq)
        for length in (2, 3):
            if seq_len < length:
                continue
            for i in range(seq_len - length + 1):
                phrase = seq[i:i + length]
                if phrase in STOP_PHRASES or len(set(phrase)) == 1:
                    continue
                counter[phrase] += 1

    return {
        "total_cjk": n,
        "sentence_count": len(sents),
        "avg_sentence_chars": round(sum(slens) / len(slens), 1),
        "para_median": med,
        "ultrashort_pct": round(ultra / len(plens) * 100, 1) if paras else 0.0,
        "dialogue_ratio": dialogue_ratio,
        "dialogue_pct": round(dialogue_ratio * 100, 1),
        "exclaim_per_wan": per_wan(text.count("！")),
        "question_per_wan": per_wan(text.count("？")),
        "ellipsis_per_wan": per_wan(text.count("……")),
        "metaphor_per_wan": per_wan(len(METAPHOR_RE.findall(text))),
        "emdash_per_wan": per_wan(len(EMDASH_RE.findall(text))),
        "bushi_count": len(BUSHI_RE.findall(text)),
        "perspective": "第一人称" if first_p > third_p else "第三人称",
        "dao_hits": DAO_RE.findall(text),
        "shuo_hits": SHUO_RE.findall(text),
        "top_phrases": counter.most_common(12),
        "ai_vocab_hits": {w: text.count(w) for w in AI_VOCAB if w in text},
    }


def _build_profile(entries: List[Dict[str, object]]) -> Dict[str, object]:
    text = "\n\n".join(str(e["text"]) for e in entries)
    m = _compute(text)

    # 判定区间：以语料实测值为中枢，±50% 为容忍带
    band = lambda v: (round(v * 0.5, 1), round(v * 1.5, 1))
    sent_lo = max(10, round(m["avg_sentence_chars"] * 0.6, 1))
    sent_hi = round(m["avg_sentence_chars"] * 1.4, 1)
    para_lo = max(15, round(m["para_median"] * 0.55, 1))
    para_hi = round(m["para_median"] * 1.6, 1)

    # 对话动词体系：
    # - 只有一方出现 → 硬约束（另一方出现即 FAIL）
    # - 两方都出现 → 混合体系，不设硬 FAIL，仅提示倾向
    shuo_n = len(m["shuo_hits"])
    dao_n = len(m["dao_hits"])
    if dao_n > 0 and shuo_n == 0:
        verb_system = "dao"
    elif shuo_n > 0 and dao_n == 0:
        verb_system = "shuo"
    else:
        verb_system = "mixed"

    return {
        "author": None,  # 由 build 填充
        "metrics": {
            "avg_sentence_chars": m["avg_sentence_chars"],
            "para_median": m["para_median"],
            "ultrashort_pct": m["ultrashort_pct"],
            "dialogue_pct": m["dialogue_pct"],
            "exclaim_per_wan": m["exclaim_per_wan"],
            "question_per_wan": m["question_per_wan"],
            "ellipsis_per_wan": m["ellipsis_per_wan"],
            "metaphor_per_wan": m["metaphor_per_wan"],
            "emdash_per_wan": m["emdash_per_wan"],
            "perspective": m["perspective"],
            "dao_count": dao_n,
            "shuo_count": shuo_n,
            "top_phrases": m["top_phrases"],
            "ai_vocab_hits": m["ai_vocab_hits"],
        },
        "bands": {
            "avg_sentence_chars": (sent_lo, sent_hi),
            "para_median": (para_lo, para_hi),
            "ultrashort_pct": (0, round(m["ultrashort_pct"] * 2.2, 1)),
            "exclaim_per_wan": band(m["exclaim_per_wan"]),
            "question_per_wan": band(m["question_per_wan"]),
            "ellipsis_per_wan": band(m["ellipsis_per_wan"]),
            "metaphor_per_wan": band(m["metaphor_per_wan"]),
            "emdash_per_wan": (0, round(m["emdash_per_wan"] * 2.0 + 2, 1)),
        },
        "rules": {
            "dialogue_verb_system": verb_system,
            "dao_allowed": dao_n > 0,
            "shuo_allowed": shuo_n > 0,
            "perspective": m["perspective"],
            "ai_vocab_blacklist": [],  # 作者皮肤层不套通用防 AI 词表（见 build_skin 说明）
            "bushi_max": max(1, m["bushi_count"]),
        },
    }


def _render_rules(profile: Dict[str, object], author: str) -> str:
    met = profile["metrics"]
    bands = profile["bands"]
    rules = profile["rules"]

    lines = [
        f"# 风格档案：{author}",
        "",
        f"> 由 style_profile.py 从语料自动生成。写作时加载本文件作为约束；写完后用 style_audit.py 审计。",
        "",
        "## 核心指标",
        f"- 平均句长：{met['avg_sentence_chars']} 字（容忍带 {bands['avg_sentence_chars'][0]}~{bands['avg_sentence_chars'][1]}）",
        f"- 段落长度中位数：{met['para_median']} 字（容忍带 {bands['para_median'][0]}~{bands['para_median'][1]}）",
        f"- 超短段(≤15字)占比：{met['ultrashort_pct']}%（上限 {bands['ultrashort_pct'][1]}%）",
        f"- 对话占比：{met['dialogue_pct']}%",
        f"- 感叹号/万字：{met['exclaim_per_wan']}（{bands['exclaim_per_wan']}）",
        f"- 问号/万字：{met['question_per_wan']}（{bands['question_per_wan']}）",
        f"- 省略号/万字：{met['ellipsis_per_wan']}（{bands['ellipsis_per_wan']}）",
        f"- 比喻标记(像是/仿佛/似的)/万字：{met['metaphor_per_wan']}（{bands['metaphor_per_wan']}）",
        f"- 句内破折号/万字：{met['emdash_per_wan']}（上限 {bands['emdash_per_wan'][1]}）",
        f"- 叙述视角：{met['perspective']}",
        "",
        "## 硬性规则（违反即穿帮，FAIL）",
        f"- 对话动词体系：**{rules['dialogue_verb_system']}**",
        f"  - 说系：{'允许' if rules['shuo_allowed'] else '禁用'}（语料出现 {met['shuo_count']} 处）",
        f"  - 道系：{'允许' if rules['dao_allowed'] else '禁用'}（语料出现 {met['dao_count']} 处）",
    ]

    if rules["ai_vocab_blacklist"]:
        lines += [
            "",
            "### AI 味黑名单（语料中高频出现，成文禁用）",
            "、".join(rules["ai_vocab_blacklist"]),
        ]

    if met["top_phrases"]:
        top = "、".join(f"{w}({c})" for w, c in met["top_phrases"][:10])
        lines += ["", "## 高频短语", top]

    lines += [
        "",
        "## 写作动作建议",
        f"1. 句长控制：以 {met['avg_sentence_chars']} 字为中枢，长句不超 {bands['avg_sentence_chars'][1]} 字。",
        f"2. 段落节奏：中位数 {met['para_median']} 字，短段(≤15字)占比控制在 {met['ultrashort_pct']}% 附近。",
        f"3. 对话比例：约 {met['dialogue_pct']}%，偏离时优先调文体而非剧情。",
        f"4. 视角：默认 {met['perspective']}，切视角必须给章节理由。",
        "5. 破折号是懒人连接符：超上限时改回句号/逗号。",
    ]
    return "\n".join(lines)


def _load_corpus(authors_root: Path, author: str, kind: str) -> str:
    """读取分离语料：kind='narrative' 或 'dialogue'。"""
    a_dir = authors_root / _slug(author)
    corpus_path = a_dir / "corpus" / f"{kind}.txt"
    if not corpus_path.exists():
        return ""
    return corpus_path.read_text(encoding="utf-8", errors="ignore")


def _render_skin_md(author: str, metrics: Dict[str, object], bands: Dict[str, object]) -> str:
    met = metrics
    return f"""# 语言皮肤 · {author}

> 从纯叙述语料提取（narrative.txt，已剔除对话）。这是"真文风"——只含句法/节奏/标点/比喻，
> 不含任何角色人格。跨作品可复用。

## 核心指标（叙述层）
- 平均句长：{met['avg_sentence_chars']} 字（容忍带 {bands['avg_sentence_chars'][0]}~{bands['avg_sentence_chars'][1]}）
- 段落长度中位数：{met['para_median']} 字（容忍带 {bands['para_median'][0]}~{bands['para_median'][1]}）
- 超短段(≤15字)占比：{met['ultrashort_pct']}%（上限 {bands['ultrashort_pct'][1]}%）
- 感叹号/万字：{met['exclaim_per_wan']}（{bands['exclaim_per_wan']}）
- 问号/万字：{met['question_per_wan']}（{bands['question_per_wan']}）
- 省略号/万字：{met['ellipsis_per_wan']}（{bands['ellipsis_per_wan']}）
- 比喻标记/万字：{met['metaphor_per_wan']}（{bands['metaphor_per_wan']}）
- 句内破折号/万字：{met['emdash_per_wan']}（上限 {bands['emdash_per_wan'][1]}）
- 叙述视角：{met['perspective']}

## 语言皮肤规则（硬约束）
1. 句长以 {met['avg_sentence_chars']} 字为中枢，长句不超 {bands['avg_sentence_chars'][1]} 字。
2. 段落节奏：中位数 {met['para_median']} 字，短段是低频重锤，占比 ≤{bands['ultrashort_pct'][1]}%。
3. 破折号是懒人连接符：超 {bands['emdash_per_wan'][1]}/万字 时改回句号/逗号。
4. 比喻要"又准又野"，但密度控制在 {bands['metaphor_per_wan']} 区间——宁缺毋滥。
5. 视角默认 {met['perspective']}，切视角必须给章节理由。

## 叙述层高频词
{ '、'.join(f'{w}({c})' for w, c in met['top_phrases'][:10]) if met['top_phrases'] else '无' }

## AI 味黑名单（叙述层高频出现，成文禁用）
{ '、'.join(met['ai_vocab_blacklist']) if met.get('ai_vocab_blacklist') else '无' }
"""


def _render_voice_md(author: str, metrics: Dict[str, object]) -> str:
    met = metrics
    verb_sys = "说系" if len(met["shuo_hits"]) >= len(met["dao_hits"]) else "道系"
    return f"""# 角色画像 · {author}

> 从对话语料提取（dialogue.txt）。这是"叙事人格"层——只有角色说话方式，
> 不代表任何参考作品主角。**此文件必须由项目作者审核/改写**，填入本项目角色的
> 专属人格（口头禅、吐槽功能、情绪反应），不可直接沿用参考作角色。

## 对话层指标（语料实测）
- 对话动词体系：{verb_sys}（说×{len(met['shuo_hits'])}，道×{len(met['dao_hits'])}）
- 对话占比：{met['dialogue_pct']}%
- 台词句长均值：{met['avg_sentence_chars']} 字
- 感叹号/问号/省略号：{met['exclaim_per_wan']}/{met['question_per_wan']}/{met['ellipsis_per_wan']}（每万字）

## 对话层高频词
{ '、'.join(f'{w}({c})' for w, c in met['top_phrases'][:10]) if met['top_phrases'] else '无' }

## ⛔ 人格层必须人工填写的部分
> 以下四项是"角色人格"，语料统计给不出答案，必须由项目作者/编辑手动填写。

1. **角色口头禅**：________________（参考作角色的口头禅不可沿用）
2. **吐槽功能**：自嘲示弱 / 试探底牌 / 掂量利益 / 掩饰心思（选一或组合）
3. **紧张时反应**：话变碎 / 算计更密 / 沉默 / 冷笑
4. **OOC 红线**：________________（如"绝不自我贬低""不对弱者摆谱"）
"""


def build_skin(authors_root: Path, author: str) -> Dict[str, object]:
    text = _load_corpus(authors_root, author, "narrative")
    if not text.strip():
        return {"ok": False, "error": f"作者 [{author}] 无叙述语料(narrative.txt)，先运行 style_corpus.py ingest"}

    m = _compute(text)
    band = lambda v: (round(v * 0.5, 1), round(v * 1.5, 1))
    bands = {
        "avg_sentence_chars": (max(10, round(m["avg_sentence_chars"] * 0.6, 1)), round(m["avg_sentence_chars"] * 1.4, 1)),
        "para_median": (max(15, round(m["para_median"] * 0.55, 1)), round(m["para_median"] * 1.6, 1)),
        "ultrashort_pct": (0, round(m["ultrashort_pct"] * 2.2, 1)),
        "exclaim_per_wan": band(m["exclaim_per_wan"]),
        "question_per_wan": band(m["question_per_wan"]),
        "ellipsis_per_wan": band(m["ellipsis_per_wan"]),
        "metaphor_per_wan": band(m["metaphor_per_wan"]),
        "emdash_per_wan": (0, round(m["emdash_per_wan"] * 2.0 + 2, 1)),
    }
    skin = {
        "author": author,
        "layer": "skin",
        "metrics": {k: v for k, v in m.items() if k not in ("dao_hits", "shuo_hits")},
        "bands": bands,
        # 语言皮肤是"作者模仿"层，作者自己的高频词（仿佛/缓缓/微微…）就是其文风，
        # 不能套用通用防 AI 词表去禁用，否则会与"高比喻密度"等规则自相矛盾。
        "ai_vocab_blacklist": [],
        "top_phrases": m["top_phrases"],
    }

    a_dir = authors_root / _slug(author)
    a_dir.mkdir(parents=True, exist_ok=True)
    skin_path = a_dir / "skin.json"
    md_path = a_dir / "skin.md"
    skin_path.write_text(json.dumps(skin, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_skin_md(author, m, bands), encoding="utf-8")

    print(f"作者 [{author}] 语言皮肤已生成（纯叙述，零人格）:")
    print(f"  skin.json: {skin_path}")
    print(f"  skin.md:   {md_path}")
    return {"ok": True, "skin": str(skin_path), "skin_md": str(md_path)}


def build_voice(authors_root: Path, author: str) -> Dict[str, object]:
    text = _load_corpus(authors_root, author, "dialogue")
    if not text.strip():
        return {"ok": False, "error": f"作者 [{author}] 无对话语料(dialogue.txt)，先运行 style_corpus.py ingest"}

    m = _compute(text)
    voice = {
        "author": author,
        "layer": "voice",
        "metrics": {
            "dao_count": len(m["dao_hits"]),
            "shuo_count": len(m["shuo_hits"]),
            "dialogue_pct": m["dialogue_pct"],
            "avg_sentence_chars": m["avg_sentence_chars"],
            "exclaim_per_wan": m["exclaim_per_wan"],
            "question_per_wan": m["question_per_wan"],
            "ellipsis_per_wan": m["ellipsis_per_wan"],
            "top_phrases": m["top_phrases"],
        },
        "dao_hits": m["dao_hits"][:20],
        "shuo_hits": m["shuo_hits"][:20],
        "persona": {  # 人工填写区
            "口头禅": "",
            "吐槽功能": "",
            "紧张时反应": "",
            "OOC红线": [],
        },
    }

    a_dir = authors_root / _slug(author)
    a_dir.mkdir(parents=True, exist_ok=True)
    voice_path = a_dir / "voice.json"
    md_path = a_dir / "voice.md"
    voice_path.write_text(json.dumps(voice, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_voice_md(author, m), encoding="utf-8")

    print(f"作者 [{author}] 角色画像已生成（对话层指标 + 人工填写区）:")
    print(f"  voice.json: {voice_path}")
    print(f"  voice.md:   {md_path}")
    print("  ⚠️  voice.md 的『人格层必须人工填写』部分请由项目作者审核填写")
    return {"ok": True, "voice": str(voice_path), "voice_md": str(md_path)}


def build(authors_root: Path, author: str) -> Dict[str, object]:
    entries = _load_entries(authors_root, author)
    if not entries:
        return {"ok": False, "error": f"作者 [{author}] 无入库语料，先运行 style_corpus.py ingest"}

    profile = _build_profile(entries)
    profile["author"] = author
    profile["entry_count"] = len(entries)

    a_dir = authors_root / _slug(author)
    a_dir.mkdir(parents=True, exist_ok=True)
    profile_path = a_dir / "profile.json"
    rules_path = a_dir / "rules.md"

    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    rules_path.write_text(_render_rules(profile, author), encoding="utf-8")

    print(f"作者 [{author}] 档案已生成:")
    print(f"  profile.json: {profile_path}")
    print(f"  rules.md:     {rules_path}")
    return {"ok": True, "profile": str(profile_path), "rules": str(rules_path)}


def show(authors_root: Path, author: str) -> None:
    a_dir = authors_root / _slug(author)
    rules_path = a_dir / "rules.md"
    if not rules_path.exists():
        print(f"作者 [{author}] 无档案，先运行 build")
        return
    print(rules_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="风格档案生成器（皮肤/人格分离）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("build", "build-skin", "build-voice", "show"):
        p = sub.add_parser(name)
        p.add_argument("--author", required=True)
        p.add_argument("--authors-root", default=str(default_authors_dir()))
    args = parser.parse_args()

    root = Path(args.authors_root).expanduser().resolve()
    if args.cmd == "build":
        result = build(root, args.author)
        if not result.get("ok"):
            print(result.get("error", "未知错误"))
            return 1
    elif args.cmd == "build-skin":
        result = build_skin(root, args.author)
        if not result.get("ok"):
            print(result.get("error", "未知错误"))
            return 1
    elif args.cmd == "build-voice":
        result = build_voice(root, args.author)
        if not result.get("ok"):
            print(result.get("error", "未知错误"))
            return 1
    else:
        show(root, args.author)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
