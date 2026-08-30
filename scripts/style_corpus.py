#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
样章入库与场景检索（文风复刻增强层 · 原文层）

把目标作者的样章原文按"场景类型"分类入库，构建轻量检索索引。
写作时可按场景检索原文片段，直接注入提示词作为 few-shot 参考。

用法:
    python style_corpus.py ingest --author jiangnan --samples a.md b.md [--scene auto]
    python style_corpus.py search --author jiangnan --query "打斗场面" [--top 3]
    python style_corpus.py list   --author jiangnan

作者档案目录（可扩展，每作者一个子目录）:
    <skill>/authors/<author_slug>/
        corpus/narrative.txt    # 叙述语料（语言皮肤层，重建式生成）
        corpus/dialogue.txt     # 对话语料（角色画像层，重建式生成）
        index.json              # 检索索引（段落级，含场景/叙述-对话分层）

注意：ingest 是"重建式"——重复 ingest 会清空旧语料后重新入库，
不是追加式。多批样章请一次 ingest 全部传入（--samples 可多文件）。

纯标准库实现，无第三方依赖。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from paths import author_style_root

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SCENES = ["战斗", "对话", "心理", "环境", "日常", "其他"]


def _cjk_len(text: str) -> int:
    return len(CJK_RE.findall(text))


def _cjk_chars(text: str) -> List[str]:
    return CJK_RE.findall(text)


def default_authors_dir() -> Path:
    return author_style_root()


def author_dir(authors_root: Path, author: str) -> Path:
    slug = re.sub(r"[^a-z0-9_-]+", "-", author.lower()).strip("-") or "default"
    return authors_root / slug


# ---------- 场景分类 ----------

ACTION_WORDS = {"斩", "劈", "砍", "刺", "杀", "拳", "掌", "腿", "刀", "剑", "枪", "闪", "躲",
                "吼", "轰", "炸", "冲", "撞", "摔", "血", "尸体", "倒下", "逃", "追"}
MIND_WORDS = {"想", "觉得", "心", "念", "忆", "怕", "爱", "恨", "怒", "悲", "喜", "悔",
              "梦", "回忆", "沉默", "孤独", "记忆", "眼神", "哭"}
ENV_WORDS = {"天", "云", "风", "雨", "雪", "夜", "月", "光", "影", "山", "水", "树", "屋",
             "门", "窗", "灯", "城", "街", "路", "空", "雾", "烟"}


def classify_kind(paragraph: str) -> str:
    """段落分层：dialogue（含台词/引号） vs narrative（纯叙述）。

    核心原则：语言皮肤从零引号的纯叙述段提取（彻底零人格污染），
    角色画像从含对话的段落提取。凡含引号对 = 可能带出角色人格 → dialogue。
    """
    chars = _cjk_len(paragraph)
    if chars == 0:
        return "narrative"
    # 含成对引号（台词出现）即归 dialogue；兼容中文引号与 ASCII 引号
    if (paragraph.count("“") or paragraph.count("「") or paragraph.count("『")
            or paragraph.count('"') >= 2):
        return "dialogue"
    return "narrative"


def classify_scene(paragraph: str) -> str:
    """按启发式把段落分到场景类型。"""
    text = paragraph
    quotes = text.count("“") + text.count("「") + text.count("『")
    chars = _cjk_len(text)
    if chars == 0:
        return "其他"
    quote_ratio = quotes / chars

    if quote_ratio >= 0.06:  # 对话密集
        return "对话"
    action_hits = sum(1 for w in ACTION_WORDS if w in text)
    mind_hits = sum(1 for w in MIND_WORDS if w in text)
    env_hits = sum(1 for w in ENV_WORDS if w in text)
    density = lambda n: n / chars * 100

    scores = {
        "战斗": density(action_hits) * 1.5,
        "心理": density(mind_hits) * 1.3,
        "环境": density(env_hits),
    }
    best, best_score = "日常", 0.0
    for scene, score in scores.items():
        if score > best_score:
            best, best_score = scene, score
    if best_score < 0.5:
        return "日常"
    return best


# ---------- 入库 ----------


def ingest_samples(
    authors_root: Path,
    author: str,
    sample_paths: List[Path],
    scene_mode: str,
) -> Dict[str, object]:
    a_dir = author_dir(authors_root, author)
    corpus_dir = a_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # 清空旧的 corpus（重新入库）
    for f in corpus_dir.glob("*.md"):
        f.unlink()

    index: List[Dict[str, object]] = []
    stats: Dict[str, int] = Counter()
    kind_stats: Dict[str, int] = Counter()
    para_id = 0
    total_cjk = 0
    narrative_paras: List[str] = []
    dialogue_paras: List[str] = []

    for p in sample_paths:
        if not p.exists():
            print(f"样章不存在: {p}")
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        paras = [x.strip() for x in re.split(r"\n\s*\n+", text) if _cjk_len(x.strip()) >= 3]
        for para in paras:
            scene = classify_scene(para) if scene_mode == "auto" else scene_mode
            if scene not in SCENES:
                scene = "其他"
            kind = classify_kind(para)
            index.append({
                "id": f"{p.stem}-{para_id}",
                "scene": scene,
                "kind": kind,
                "text": para,
                "chars": _cjk_len(para),
            })
            stats[scene] += 1
            kind_stats[kind] += 1
            (narrative_paras if kind == "narrative" else dialogue_paras).append(para)
            total_cjk += _cjk_len(para)
            para_id += 1

    index_path = a_dir / "index.json"
    index_path.write_text(json.dumps({"author": author, "entries": index},
                                     ensure_ascii=False, indent=2), encoding="utf-8")

    # 分离语料：语言皮肤语料（narrative）+ 角色画像语料（dialogue）
    skin_corpus = a_dir / "corpus" / "narrative.txt"
    voice_corpus = a_dir / "corpus" / "dialogue.txt"
    skin_corpus.write_text("\n\n".join(narrative_paras), encoding="utf-8")
    voice_corpus.write_text("\n\n".join(dialogue_paras), encoding="utf-8")

    summary = {s: stats.get(s, 0) for s in SCENES if stats.get(s, 0)}
    print(f"作者 [{author}] 入库完成:")
    print(f"  段落数: {len(index)}  总字数: {total_cjk}")
    print(f"  场景分布: {summary}")
    print(f"  分层: narrative(语言皮肤)={kind_stats.get('narrative', 0)}段 "
          f"dialogue(角色画像)={kind_stats.get('dialogue', 0)}段")
    print(f"  索引: {index_path}")
    return {"ok": True, "total_paras": len(index), "total_chars": total_cjk,
            "scene_stats": dict(summary), "kind_stats": dict(kind_stats),
            "index": str(index_path)}


# ---------- 检索（BM25） ----------


def _tokenize(text: str) -> List[str]:
    """中文 2-gram + 标点过滤。"""
    chars = _cjk_chars(text)
    tokens = [c for c in chars]
    tokens += ["".join(chars[i:i + 2]) for i in range(len(chars) - 1)]
    return tokens


def _build_doc_tokens(entries: List[Dict[str, object]]) -> List[List[str]]:
    return [_tokenize(e["text"]) for e in entries]


def _bm25(
    query: str,
    entries: List[Dict[str, object]],
    doc_tokens: List[List[str]],
    k1: float = 1.5,
    b: float = 0.75,
) -> List[Tuple[int, float]]:
    q_tokens = set(_tokenize(query))
    n = len(entries)
    if n == 0 or not q_tokens:
        return []
    avg_len = sum(len(t) for t in doc_tokens) / n or 1.0

    df: Counter = Counter()
    for tokens in doc_tokens:
        for t in set(tokens):
            df[t] += 1

    scores: List[Tuple[int, float]] = []
    for i, tokens in enumerate(doc_tokens):
        doc_len = len(tokens)
        tf: Counter = Counter(tokens)
        score = 0.0
        for t in q_tokens:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            tf_part = tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * doc_len / avg_len))
            score += idf * tf_part
        if score > 0:
            scores.append((i, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def search(
    authors_root: Path,
    author: str,
    query: str,
    top: int,
    scene_filter: str = "",
    kind_filter: str = "",
) -> Dict[str, object]:
    a_dir = author_dir(authors_root, author)
    index_path = a_dir / "index.json"
    if not index_path.exists():
        return {"ok": False, "error": f"作者 [{author}] 尚未入库，先运行 ingest"}

    data = json.loads(index_path.read_text(encoding="utf-8"))
    entries: List[Dict[str, object]] = data["entries"]
    if scene_filter:
        entries = [e for e in entries if e["scene"] == scene_filter]
    if kind_filter:
        entries = [e for e in entries if e.get("kind") == kind_filter]
    if not entries:
        return {"ok": True, "hits": [], "query": query, "scene_filter": scene_filter,
                "kind_filter": kind_filter}

    doc_tokens = _build_doc_tokens(entries)
    hits = _bm25(query, entries, doc_tokens)[:top]
    results = [{"id": entries[i]["id"], "scene": entries[i]["scene"],
                "kind": entries[i].get("kind", "narrative"),
                "chars": entries[i]["chars"], "text": entries[i]["text"],
                "score": round(s, 3)} for i, s in hits]
    return {"ok": True, "query": query, "scene_filter": scene_filter,
            "kind_filter": kind_filter,
            "total_scored": len(hits), "hits": results}


def list_authors(authors_root: Path) -> None:
    if not authors_root.exists():
        print("尚无作者档案")
        return
    for d in sorted(authors_root.iterdir()):
        if d.is_dir():
            index = d / "index.json"
            n = 0
            if index.exists():
                n = len(json.loads(index.read_text(encoding="utf-8")).get("entries", []))
            print(f"  [{d.name}] 段落数: {n}")


def main() -> int:
    parser = argparse.ArgumentParser(description="样章入库与场景检索（文风复刻原文层）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="样章入库（按场景分类）")
    p_ingest.add_argument("--author", required=True, help="作者标识（小写英文，如 jiangnan）")
    p_ingest.add_argument("--samples", nargs="+", required=True, help="样章文件路径（可多个）")
    p_ingest.add_argument("--scene", default="auto", choices=["auto"] + SCENES, help="场景分类方式")
    p_ingest.add_argument("--authors-root", default=str(default_authors_dir()))

    p_search = sub.add_parser("search", help="按场景/关键词检索原文片段")
    p_search.add_argument("--author", required=True)
    p_search.add_argument("--query", required=True, help="检索意图，如：打斗场面")
    p_search.add_argument("--scene", default="", help="限定场景类型（可选）")
    p_search.add_argument("--kind", default="", choices=["", "narrative", "dialogue"],
                          help="限定段落类型：narrative=语言皮肤语料 / dialogue=角色画像语料")
    p_search.add_argument("--top", type=int, default=3)
    p_search.add_argument("--authors-root", default=str(default_authors_dir()))

    p_list = sub.add_parser("list", help="列出所有作者档案")
    p_list.add_argument("--authors-root", default=str(default_authors_dir()))

    args = parser.parse_args()

    root = Path(args.authors_root).expanduser().resolve()
    if args.cmd == "ingest":
        samples = [Path(p).expanduser().resolve() for p in args.samples]
        ingest_samples(root, args.author, samples, args.scene)
    elif args.cmd == "search":
        result = search(root, args.author, args.query, args.top, args.scene, args.kind)
        if not result.get("ok"):
            print(result.get("error", "未知错误"))
            return 1
        kind_tag = f"  分层: {result['kind_filter']}" if result.get("kind_filter") else ""
        print(f"查询: {result['query']}  场景: {result['scene_filter'] or '全部'}{kind_tag}")
        for h in result["hits"]:
            print(f"\n--- [{h['scene']}/{h['kind']}] {h['id']} (score={h['score']}, {h['chars']}字) ---")
            print(h["text"][:300] + ("..." if h["chars"] > 300 else ""))
        if not result["hits"]:
            print("无命中")
    elif args.cmd == "list":
        list_authors(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
