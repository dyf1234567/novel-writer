#!/usr/bin/env python3
"""轻量剧情检索器（RAG 风格，零外部依赖）。

目标：将人物关系、剧情走向与章节内容建立可检索关联，
在写新剧情前自动给出“应回读哪些章节”的上下文建议。
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from common import ensure_dir, read_text, slugify, chapter_no_from_name, normalize_text
from config import get_retrieval_config
from performance import Tokenizer

# 从集中配置加载检索相关常量
_retrieval_config = get_retrieval_config()
STOPWORDS = _retrieval_config.stopwords
TRIGGER_KEYWORDS = _retrieval_config.trigger_keywords
LIGHT_SCENE_KEYWORDS = _retrieval_config.light_scene_keywords

# 全局分词器实例（带缓存，性能优于手写版本）
_tokenizer = Tokenizer(stopwords=STOPWORDS)

# ── 检索引擎：legacy / fts5 / hybrid（FTS5 + 本地语义向量） ───────────
ENGINE_LEGACY = "legacy"
ENGINE_FTS5 = "fts5"
ENGINE_HYBRID = "hybrid"
FTS5_DB_FILENAME = "story_index.sqlite"
# 占位章标记（与 novel_flow_executor 保持同一常量值，此处独立定义避免循环导入）
_NOVEL_FLOW_STUB = "<!-- NOVEL_FLOW_STUB -->"
_BEAT_SHEET_STUB = "<!-- BEAT_SHEET_STUB -->"


def tokenize(text: str) -> List[str]:
    """中文 2~4 字 n-gram + 英文词分词，委托给优化的 Tokenizer 实现。"""
    return _tokenizer.tokenize(text)


def parse_chapter_no(filename: str) -> int:
    return chapter_no_from_name(filename)


def normalize_query(query: str) -> str:
    return normalize_text(query)


def load_character_alias_map(project_root: Path) -> Dict[str, List[str]]:
    """解析 character_tracker.md 的"别名/称谓"列，返回 正名 -> [正名, 别名...]。

    兼容列名：别名 / 称谓 / 绰号 / 外号；别名按 、，, / 空白 分隔。
    无别名列时返回空映射，不影响既有行为。
    """
    p = project_root / "00_memory" / "character_tracker.md"
    if not p.exists():
        return {}
    txt = read_text(p)

    alias_col: Optional[int] = None
    alias_keys = ("别名", "称谓", "绰号", "外号")
    result: Dict[str, List[str]] = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if alias_col is None:
            for i, c in enumerate(cells):
                if any(k in c for k in alias_keys):
                    alias_col = i
                    break
            continue
        if len(cells) <= alias_col:
            continue
        name = cells[0]
        if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·]{2,20}", name):
            continue
        raw = cells[alias_col]
        aliases = [
            a for a in re.split(r"[、，,/\s]+", raw)
            if a and len(a) >= 2 and a != name
        ]
        if aliases:
            result[name] = [name] + aliases
    return result


def _entities_in_text(text: str, names: List[str], alias_map: Optional[Dict[str, List[str]]] = None) -> List[str]:
    """实体命中检测：正名或任一别名出现在文本中，归一为正名返回。"""
    alias_map = alias_map or {}
    return [
        n for n in names
        if any(t and t in text for t in (alias_map.get(n) or [n]))
    ]


def _load_graph_neighbors(project_root: Path) -> Dict[str, List[str]]:
    """从 story_graph.json 构建角色邻接表：角色名 -> [邻居角色名]。

    仅统计角色节点间的边（忽略 type 差异，宽容处理缺失 name 的节点）。
    """
    graph_file = project_root / "00_memory" / "story_graph.json"
    if not graph_file.exists():
        return {}
    try:
        graph = json.loads(graph_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(graph, dict):
        return {}
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    id2name: Dict[str, str] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        if nid:
            id2name[nid] = str(n.get("name") or "") or nid
    neighbors: Dict[str, List[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        s = id2name.get(str(e.get("source") or ""))
        t = id2name.get(str(e.get("target") or ""))
        if s and t and s != t:
            neighbors.setdefault(s, []).append(t)
            neighbors.setdefault(t, []).append(s)
    return {k: list(dict.fromkeys(v)) for k, v in neighbors.items()}


def analyze_query_trigger(query: str, names: List[str], alias_map: Optional[Dict[str, List[str]]] = None) -> Dict[str, object]:
    q = normalize_query(query)
    alias_map = alias_map or {}
    # 别名扩展：正名或任一别名命中都算实体命中（归并到正名）
    entities = [
        n for n in names
        if any(t and t in q for t in (alias_map.get(n) or [n]))
    ]
    keyword_hits = sorted([k for k in TRIGGER_KEYWORDS if k in q])
    light_hits = sorted([k for k in LIGHT_SCENE_KEYWORDS if k in q])
    long_query = len(q) >= 18

    should = bool(entities or keyword_hits or (long_query and not light_hits))
    reason = []
    if entities:
        reason.append(f"命中角色:{','.join(entities)}")
    if keyword_hits:
        reason.append(f"命中剧情关键词:{','.join(keyword_hits[:4])}")
    if long_query and not light_hits:
        reason.append("查询描述较长，判定为复杂剧情")
    if light_hits and not entities and not keyword_hits:
        reason.append(f"仅命中轻场景关键词:{','.join(light_hits)}")
    if not reason:
        reason.append("未命中角色/剧情关键词，判定为可跳过检索")

    return {
        "should_trigger": should,
        "entities": entities,
        "keyword_hits": keyword_hits,
        "light_hits": light_hits,
        "query_length": len(q),
        "reason": reason,
    }


def load_character_names(project_root: Path) -> List[str]:
    p = project_root / "00_memory" / "character_tracker.md"
    if not p.exists():
        return []
    txt = read_text(p)

    names = set()

    # 1) 表格第一列
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        candidate = cells[0]
        if candidate in {"人物", "角色", "姓名", "---", ""}:
            continue
        if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·]{2,20}", candidate):
            names.add(candidate)

    # 2) “姓名: xxx”形式
    for m in re.finditer(r"(?:姓名|角色)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9_·]{2,20})", txt):
        names.add(m.group(1).strip())

    # 去噪
    bad = {"当前状态", "关系", "位置", "目标", "变化", "章节"}
    names = {n for n in names if n not in bad}
    return sorted(names)


def extract_relation_snippets(path: Path, terms: List[str], window: int = 2, max_hits: int = 8) -> List[str]:
    # 参数校验
    if window < 0:
        raise ValueError(f"window 必须非负，当前值: {window}")
    if max_hits < 0:
        raise ValueError(f"max_hits 必须非负，当前值: {max_hits}")
    if not path.exists() or not terms:
        return []
    lines = read_text(path).splitlines()
    hits: List[str] = []
    used = set()
    seen_blocks = set()
    last_end = -1
    for i, line in enumerate(lines):
        if not any(t in line for t in terms):
            continue
        if i <= last_end:
            continue
        start = max(0, i - window)
        end = min(len(lines), i + window + 1)
        key = (start, end)
        if key in used:
            continue
        used.add(key)
        block = "\n".join(lines[start:end]).strip()
        normalized_lines = []
        for ln in block.splitlines():
            s = ln.strip()
            if re.fullmatch(r"\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?", s):
                continue
            if s:
                normalized_lines.append(s)
        norm_key = " || ".join(normalized_lines)

        if block and norm_key and norm_key not in seen_blocks:
            hits.append(block)
            seen_blocks.add(norm_key)
            last_end = end - 1
        if len(hits) >= max_hits:
            break
    return hits


def split_passages(text: str, max_chars: int = 360) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paragraphs:
        paragraphs = [normalize_text(text)]

    passages: List[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            passages.append(para)
            continue
        # 超长段落按句子切片，避免整段回读。
        pieces = [s.strip() for s in re.split(r"(?<=[。！？!?])", para) if s.strip()]
        buf = ""
        for piece in pieces:
            if len(buf) + len(piece) <= max_chars:
                buf += piece
            else:
                if buf:
                    passages.append(buf)
                buf = piece
        if buf:
            passages.append(buf)
    return passages


def extract_location_candidates(text: str, top_n: int = 6) -> List[str]:
    # 轻量地点抽取：匹配“在X/到X/从X”及“X站/港/城/街/村/馆”等后缀。
    hits = []
    for m in re.finditer(r"(?:在|到|从|回到)([\u4e00-\u9fff]{2,12}(?:站台|车站|港区|港|城|城北|街|巷|村|楼|馆|厂|桥|学校|医院))", text):
        hits.append(m.group(1))
    for m in re.finditer(r"([\u4e00-\u9fff]{2,10}(?:站台|车站|港区|港|城|街|巷|村|楼|馆|厂|桥|学校|医院))", text):
        hits.append(m.group(1))
    if not hits:
        return []
    counter = Counter(hits)
    return [x for x, _ in counter.most_common(top_n)]


def infer_conflict_level(text: str) -> str:
    high = {"决战", "追杀", "爆炸", "死亡", "复活", "背叛", "崩溃", "危机", "反转"}
    medium = {"冲突", "争执", "对峙", "潜入", "调查", "追踪", "怀疑", "联盟"}
    low = {"日常", "休整", "过渡", "闲聊", "铺垫"}
    if any(k in text for k in high):
        return "high"
    if any(k in text for k in medium):
        return "medium"
    if any(k in text for k in low):
        return "low"
    return "unknown"


def build_chapter_meta(
    chapter_path: Path,
    text: str,
    chapter_no: int,
    names: List[str],
    retrieval_dir: Path,
    alias_map: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, object]:
    entities = _entities_in_text(text, names, alias_map)
    tokens = tokenize(text)
    top_tokens = [k for k, _ in Counter(tokens).most_common(18)]
    events = [k for k in TRIGGER_KEYWORDS if k in text][:10]
    locations = extract_location_candidates(text, top_n=6)
    foreshadow_refs = []
    for m in re.finditer(r"(伏笔|线索|坐标|编号|暗号|名单)[^。！？\n]{0,32}", text):
        frag = normalize_text(m.group(0))
        if frag and frag not in foreshadow_refs:
            foreshadow_refs.append(frag)
        if len(foreshadow_refs) >= 6:
            break

    meta_dir = retrieval_dir / "chapter_meta"
    ensure_dir(meta_dir)
    # 稳定 ID 命名：不依赖中文标题 slug，章节标题改名不影响检索元数据
    meta_path = meta_dir / f"ch{chapter_no:04d}.meta.json"

    flat = re.sub(r"\s+", " ", text).strip()
    meta = {
        "chapter_file": chapter_path.name,
        "chapter_path": str(chapter_path),
        "chapter_no": chapter_no,
        "mtime": chapter_path.stat().st_mtime,
        "summary": flat[:220],
        "entities": entities,
        "events": events,
        "locations": locations,
        "foreshadow_refs": foreshadow_refs,
        "keywords": top_tokens,
        "conflict_level": infer_conflict_level(text),
        "meta_file": str(meta_path),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def score_passage(
    passage: str,
    query_tokens: List[str],
    query_entities: List[str],
    alias_map: Optional[Dict[str, List[str]]] = None,
) -> Tuple[float, Dict[str, int]]:
    p_tokens = set(tokenize(passage))
    token_overlap = len(set(query_tokens) & p_tokens)
    alias_map = alias_map or {}
    entity_overlap = sum(
        1 for e in query_entities
        if any(t and t in passage for t in (alias_map.get(e) or [e]))
    )
    score = entity_overlap * 3.0 + token_overlap * 1.0
    return score, {
        "token_overlap": token_overlap,
        "entity_overlap": entity_overlap,
    }


def top_passages(
    chapter_path: Path,
    query_tokens: List[str],
    query_entities: List[str],
    per_chapter: int,
    passage_max_chars: int,
    alias_map: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, object]]:
    text = read_text(chapter_path)
    passages = split_passages(text)
    scored = []
    for p in passages:
        s, reason = score_passage(p, query_tokens, query_entities, alias_map)
        scored.append((s, reason, p))
    scored.sort(key=lambda x: x[0], reverse=True)

    selected = [x for x in scored if x[0] > 0][:per_chapter]
    if not selected:
        selected = scored[: min(per_chapter, len(scored))]

    result = []
    for s, reason, p in selected:
        short = p if len(p) <= passage_max_chars else p[:passage_max_chars].rstrip() + "..."
        result.append({
            "score": round(s, 3),
            "reason": reason,
            "text": short,
        })
    return result


def index_signature(index: Dict[str, object]) -> str:
    docs = index.get("docs", [])
    raw = "|".join(
        f"{d.get('chapter_file','')}:{d.get('mtime',0)}"
        for d in docs
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    # 角色签名纳入索引签名：角色表变化后查询缓存必须失效
    character_sig = str(index.get("character_sig", ""))[:8]
    return f"{len(docs)}-{digest}-cs{character_sig}"


def load_cache(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"entries": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {"entries": {}}
        obj.setdefault("entries", {})
        return obj
    except json.JSONDecodeError:
        return {"entries": {}}
    except (IOError, OSError):
        return {"entries": {}}


def save_cache(path: Path, cache: Dict[str, object], max_entries: int = 200) -> None:
    entries = cache.get("entries", {})
    if isinstance(entries, dict) and len(entries) > max_entries:
        items = sorted(entries.items(), key=lambda kv: kv[1].get("saved_at", ""), reverse=True)
        cache["entries"] = dict(items[:max_entries])
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def make_cache_key(query: str, top_k: int, per_chapter: int, passage_max_chars: int, idx_sig: str) -> str:
    raw = f"{normalize_query(query)}|{top_k}|{per_chapter}|{passage_max_chars}|{idx_sig}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cleanup_stale_meta_files(retrieval_dir: Path, docs: List[Dict[str, object]]) -> int:
    meta_dir = retrieval_dir / "chapter_meta"
    if not meta_dir.exists():
        return 0
    valid_files = set()
    for d in docs:
        mf = d.get("meta_file")
        if isinstance(mf, str) and mf:
            valid_files.add(Path(mf).resolve())
    removed = 0
    for p in meta_dir.glob("*.meta.json"):
        if p.resolve() not in valid_files:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def build_index(project_root: Path, keyword_top_n: int = 20, incremental: bool = True) -> Dict[str, object]:
    manuscript_dir = project_root / "03_manuscript"
    retrieval_dir = project_root / "00_memory" / "retrieval"
    ensure_dir(retrieval_dir)
    index_file = retrieval_dir / "story_index.json"

    chapters = sorted(manuscript_dir.glob("*.md"), key=lambda p: (parse_chapter_no(p.name), p.name))
    names = load_character_names(project_root)
    alias_map = load_character_alias_map(project_root)

    existing_docs: Dict[str, Dict[str, object]] = {}
    old_character_sig = ""
    if incremental and index_file.exists():
        try:
            old = json.loads(index_file.read_text(encoding="utf-8"))
            old_character_sig = str(old.get("character_sig", ""))
            for d in old.get("docs", []):
                chapter_file = str(d.get("chapter_file", ""))
                if chapter_file:
                    existing_docs[chapter_file] = d
        except Exception:
            existing_docs = {}

    character_sig = hashlib.sha1(("|".join(names)).encode("utf-8")).hexdigest()[:16]
    reuse_allowed = (old_character_sig == character_sig) if old_character_sig else True

    docs = []
    reused_docs = 0
    rebuilt_docs = 0

    for path in chapters:
        mtime = path.stat().st_mtime
        cached = existing_docs.get(path.name)
        if reuse_allowed and cached and float(cached.get("mtime", -1)) == mtime:
            doc = cached
            meta_file = doc.get("meta_file")
            if not meta_file or not Path(str(meta_file)).exists():
                text = read_text(path)
                meta = build_chapter_meta(
                    chapter_path=path,
                    text=text,
                    chapter_no=parse_chapter_no(path.name),
                    names=names,
                    retrieval_dir=retrieval_dir,
                    alias_map=alias_map,
                )
                doc.update({
                    "meta_file": meta.get("meta_file"),
                    "events": meta.get("events", []),
                    "locations": meta.get("locations", []),
                    "foreshadow_refs": meta.get("foreshadow_refs", []),
                    "conflict_level": meta.get("conflict_level", "unknown"),
                })
            reused_docs += 1
        else:
            text = read_text(path)
            flat = re.sub(r"\s+", " ", text).strip()
            summary = flat[:260]

            tokens = tokenize(text)
            top_keywords = [k for k, _ in Counter(tokens).most_common(keyword_top_n)]

            hit_entities = _entities_in_text(text, names, alias_map)
            meta = build_chapter_meta(
                chapter_path=path,
                text=text,
                chapter_no=parse_chapter_no(path.name),
                names=names,
                retrieval_dir=retrieval_dir,
                alias_map=alias_map,
            )
            doc = {
                "chapter_file": path.name,
                "chapter_path": str(path),
                "chapter_no": parse_chapter_no(path.name),
                "mtime": mtime,
                "summary": summary,
                "entities": hit_entities,
                "keywords": top_keywords,
                "meta_file": meta.get("meta_file"),
                "events": meta.get("events", []),
                "locations": meta.get("locations", []),
                "foreshadow_refs": meta.get("foreshadow_refs", []),
                "conflict_level": meta.get("conflict_level", "unknown"),
            }
            rebuilt_docs += 1
        docs.append(doc)

    docs.sort(key=lambda d: (int(d.get("chapter_no", 0)), str(d.get("chapter_file", ""))))
    entity_map: Dict[str, List[str]] = {n: [] for n in names}
    for d in docs:
        chapter_file = str(d.get("chapter_file", ""))
        for n in d.get("entities", []):
            entity_map.setdefault(n, []).append(chapter_file)
    cleaned_meta_files = cleanup_stale_meta_files(retrieval_dir, docs)

    index = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(project_root),
        "chapter_count": len(docs),
        "reused_docs": reused_docs,
        "rebuilt_docs": rebuilt_docs,
        "cleaned_meta_files": cleaned_meta_files,
        "character_sig": character_sig,
        "docs": docs,
    }

    (retrieval_dir / "story_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (retrieval_dir / "entity_chapter_map.json").write_text(json.dumps(entity_map, ensure_ascii=False, indent=2), encoding="utf-8")

    return index


def score_doc_coarse(
    doc: Dict[str, object],
    query_tokens: List[str],
    query_token_set: set,
    query_entities: List[str],
    query_text: str,
) -> Tuple[float, Dict[str, object]]:
    kw = set(doc.get("keywords", []))
    ent = set(doc.get("entities", []))
    evt = set(doc.get("events", []))
    loc = set(doc.get("locations", []))

    token_overlap = len(query_token_set & kw)
    entity_overlap = len(set(query_entities) & ent)
    event_overlap = sum(1 for e in evt if e and e in query_text)
    location_overlap = sum(1 for l in loc if l and l in query_text)

    score = entity_overlap * 4.0 + event_overlap * 2.0 + location_overlap * 1.5 + token_overlap * 1.0
    reason = {
        "token_overlap": token_overlap,
        "entity_overlap": entity_overlap,
        "event_overlap": event_overlap,
        "location_overlap": location_overlap,
    }
    return score, reason


def score_doc_fine(
    doc: Dict[str, object],
    query_tokens: List[str],
    query_token_set: set,
    query_entities: List[str],
    query_text: str,
    max_no: int,
) -> Tuple[float, Dict[str, object]]:
    kw = set(doc.get("keywords", []))
    ent = set(doc.get("entities", []))
    evt = set(doc.get("events", []))
    summary = str(doc.get("summary", ""))

    token_overlap = len(query_token_set & kw)
    summary_overlap = len(query_token_set & set(tokenize(summary)))
    entity_overlap = len(set(query_entities) & ent)
    event_overlap = sum(1 for e in evt if e and e in query_text)

    chapter_no = int(doc.get("chapter_no", 0))
    recency = (chapter_no / max_no) if max_no > 0 else 0.0
    conflict_bonus = 0.2 if doc.get("conflict_level") in {"high", "medium"} else 0.0

    score = (
        entity_overlap * 3.0
        + event_overlap * 1.8
        + token_overlap * 1.0
        + summary_overlap * 0.6
        + recency * 0.3
        + conflict_bonus
    )
    reason = {
        "token_overlap": token_overlap,
        "summary_overlap": summary_overlap,
        "entity_overlap": entity_overlap,
        "event_overlap": event_overlap,
        "recency": round(recency, 3),
        "conflict_bonus": conflict_bonus,
    }
    return score, reason


def retrieve(
    index: Dict[str, object],
    project_root: Path,
    query: str,
    top_k: int,
    candidate_k: int,
    per_chapter: int,
    passage_max_chars: int,
) -> Dict[str, object]:
    docs = index.get("docs", [])
    query_tokens = tokenize(query)
    query_token_set = set(query_tokens)
    names = load_character_names(project_root)
    alias_map = load_character_alias_map(project_root)
    # 别名扩展：正名或任一别名命中查询，归并为正名参与打分
    query_entities = _entities_in_text(query, names, alias_map)

    # 图谱邻接召回：查询实体的邻居角色所在章节强制进入候选池（词面可零重叠）
    neighbors = _load_graph_neighbors(project_root)
    neighbor_set = {nb for e in query_entities for nb in neighbors.get(e, [])}
    entity_chapter_map: Dict[str, List[str]] = {}
    emap_file = project_root / "00_memory" / "retrieval" / "entity_chapter_map.json"
    if emap_file.exists():
        try:
            emap_data = json.loads(emap_file.read_text(encoding="utf-8"))
            if isinstance(emap_data, dict):
                entity_chapter_map = {
                    str(k): [str(x) for x in v]
                    for k, v in emap_data.items() if isinstance(v, list)
                }
        except Exception:
            entity_chapter_map = {}
    graph_recall_files: List[str] = []
    for e in query_entities:
        for nb in neighbors.get(e, []):
            graph_recall_files.extend(entity_chapter_map.get(nb, []))
    graph_recall_files = list(dict.fromkeys(graph_recall_files))

    max_no = max((int(d.get("chapter_no", 0)) for d in docs), default=0)
    coarse_scored = []
    for d in docs:
        s, reason = score_doc_coarse(d, query_tokens, query_token_set, query_entities, query)
        coarse_scored.append((s, reason, d))

    coarse_scored.sort(key=lambda x: x[0], reverse=True)
    candidate_pool = [x for x in coarse_scored if x[0] > 0][:candidate_k]
    if not candidate_pool:
        candidate_pool = coarse_scored[: min(candidate_k, len(coarse_scored))]

    # 图谱邻居章节强制入池（即使粗筛零分）
    pool_files = {str(d.get("chapter_file")) for _, _, d in candidate_pool}
    for d in docs:
        cf = str(d.get("chapter_file", ""))
        if cf in graph_recall_files and cf not in pool_files:
            candidate_pool.append((0.0, {"token_overlap": 0, "entity_overlap": 0}, d))
            pool_files.add(cf)

    fine_scored = []
    for _, _, d in candidate_pool:
        s, reason = score_doc_fine(d, query_tokens, query_token_set, query_entities, query, max_no)
        fine_scored.append((s, reason, d))

    # 图谱邻居加分：章节实体与查询实体邻居的交集数量 × 0.5
    if neighbor_set:
        for i in range(len(fine_scored)):
            s, reason, d = fine_scored[i]
            d_entities = set(d.get("entities", []))
            bonus = 0.5 * len(neighbor_set & d_entities)
            if bonus:
                fine_scored[i] = (s + bonus, reason, d)
        fine_scored.sort(key=lambda x: x[0], reverse=True)

    picked = [x for x in fine_scored if x[0] > 0][:top_k]
    if not picked:
        picked = fine_scored[: min(top_k, len(fine_scored))]

    character_tracker = project_root / "00_memory" / "character_tracker.md"
    relation_snippets = extract_relation_snippets(character_tracker, query_entities)

    total_chars = 0
    retrieved = []
    for s, reason, d in picked:
        passages = top_passages(
            Path(str(d.get("chapter_path", ""))),
            query_tokens,
            query_entities,
            per_chapter=per_chapter,
            passage_max_chars=passage_max_chars,
            alias_map=alias_map,
        )
        total_chars += sum(len(str(p.get("text", ""))) for p in passages)
        retrieved.append({
            "score": round(s, 3),
            "reason": reason,
            "chapter_file": d.get("chapter_file"),
            "chapter_path": d.get("chapter_path"),
            "summary": d.get("summary", ""),
            "entities": d.get("entities", []),
            "events": d.get("events", []),
            "locations": d.get("locations", []),
            "foreshadow_refs": d.get("foreshadow_refs", []),
            "passages": passages,
        })

    return {
        "query": query,
        "query_entities": query_entities,
        "index_signature": index_signature(index),
        "retrieved": retrieved,
        "relation_snippets": relation_snippets,
        "retrieval_stats": {
            "docs_total": len(docs),
            "candidate_pool": len(candidate_pool),
            "rerank_topk": len(retrieved),
            "estimated_context_chars": total_chars,
        },
    }


# =============================================================================
# FTS5 引擎：片段级索引（SQLite） + BM25 召回 + 加权重排
# 与 legacy 引擎输出完全相同的检索结果结构（retrieved / relation_snippets /
# retrieval_stats），executor 无需感知后端差异。
# =============================================================================


def split_passages_with_offsets(text: str, max_chars: int = 450) -> List[Tuple[int, int, str]]:
    """片段级切片：按段落/句子边界切分，返回 (start_char, end_char, passage_text)。

    end 为开区间；start/end 仅为信息性偏移（供定位原文），检索正确性依赖
    存储的 passage 文本本身。
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    passages: List[Tuple[int, int, str]] = []
    for para in paragraphs:
        para_start = text.find(para)
        if para_start < 0:
            para_start = 0
        if len(para) <= max_chars:
            passages.append((para_start, para_start + len(para), para))
            continue
        pieces = [s.strip() for s in re.split(r"(?<=[。！？!?])", para) if s.strip()]
        buf = ""
        buf_start = para_start
        for piece in pieces:
            piece_start = para_start + para.find(piece)
            if len(buf) + len(piece) <= max_chars:
                if not buf:
                    buf_start = piece_start
                buf += piece
            else:
                if buf:
                    passages.append((buf_start, buf_start + len(buf), buf))
                buf_start = piece_start
                buf = piece
        if buf:
            passages.append((buf_start, buf_start + len(buf), buf))
    return passages


def _fts5_connect(retrieval_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(retrieval_dir / FTS5_DB_FILENAME))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _fts5_init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS fts_meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS fts_chapters(
        chapter_file TEXT PRIMARY KEY,
        chapter_no INTEGER,
        mtime REAL,
        summary TEXT,
        entities TEXT,
        events TEXT,
        locations TEXT,
        conflict_level TEXT
    );
    CREATE TABLE IF NOT EXISTS passages(
        passage_id TEXT PRIMARY KEY,
        chapter_no INTEGER,
        chapter_file TEXT,
        chapter_path TEXT,
        start_char INTEGER,
        end_char INTEGER,
        text TEXT,
        entities TEXT,
        events TEXT,
        locations TEXT,
        conflict_level TEXT,
        status TEXT DEFAULT 'published',
        mtime REAL
    );
    CREATE INDEX IF NOT EXISTS idx_passages_chapter ON passages(chapter_no);
    CREATE INDEX IF NOT EXISTS idx_passages_file ON passages(chapter_file);
    CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
        passage_id UNINDEXED,
        chapter_no UNINDEXED,
        chapter_file UNINDEXED,
        text,
        entities,
        events,
        locations
    );
    """)


def fts5_build_index(
    project_root: Path,
    keyword_top_n: int = 20,
    incremental: bool = True,
) -> Dict[str, object]:
    """FTS5 片段级索引构建。

    中文经 2~4 字 n-gram 预分词后以空格连接写入 FTS5（unicode61 不做中文分词），
    使 IDF / 文档频率 / BM25 真正生效。占位章（NOVEL_FLOW_STUB / BEAT_SHEET_STUB）
    一律不进入索引。
    """
    manuscript_dir = project_root / "03_manuscript"
    retrieval_dir = project_root / "00_memory" / "retrieval"
    ensure_dir(retrieval_dir)
    names = load_character_names(project_root)
    alias_map = load_character_alias_map(project_root)
    character_sig = hashlib.sha1(("|".join(names)).encode("utf-8")).hexdigest()[:16]

    chapters = sorted(manuscript_dir.glob("*.md"), key=lambda p: (parse_chapter_no(p.name), p.name))
    conn = _fts5_connect(retrieval_dir)
    reused = rebuilt = skipped_stubs = 0
    try:
        _fts5_init_schema(conn)
        current_files: set = set()
        for path in chapters:
            no = parse_chapter_no(path.name)
            if no <= 0:
                skipped_stubs += 1
                continue
            current_files.add(path.name)
            text = read_text(path)
            if _NOVEL_FLOW_STUB in text or _BEAT_SHEET_STUB in text:
                skipped_stubs += 1
                continue
            mtime = path.stat().st_mtime
            row = conn.execute(
                "SELECT mtime FROM fts_chapters WHERE chapter_file=?", (path.name,)
            ).fetchone()
            if incremental and row and abs(float(row[0]) - mtime) < 1e-6:
                reused += 1
                continue

            conn.execute("DELETE FROM passages WHERE chapter_file=?", (path.name,))
            conn.execute("DELETE FROM passage_fts WHERE chapter_file=?", (path.name,))

            flat = re.sub(r"\s+", " ", text).strip()
            entities = _entities_in_text(text, names, alias_map)
            events = [k for k in TRIGGER_KEYWORDS if k in text][:10]
            locations = extract_location_candidates(text, top_n=6)
            conflict_level = infer_conflict_level(text)
            ent_toks = " ".join(entities)
            evt_toks = " ".join(events)
            loc_toks = " ".join(locations)

            for idx, (s, e, ptext) in enumerate(split_passages_with_offsets(text), 1):
                pid = f"ch{no:04d}-p{idx:03d}"
                tokens_joined = " ".join(tokenize(ptext))
                conn.execute(
                    "INSERT INTO passages (passage_id, chapter_no, chapter_file, chapter_path,"
                    " start_char, end_char, text, entities, events, locations, conflict_level, status, mtime)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, no, path.name, str(path), s, e, ptext,
                     json.dumps(entities, ensure_ascii=False),
                     json.dumps(events, ensure_ascii=False),
                     json.dumps(locations, ensure_ascii=False),
                     conflict_level, "published", mtime),
                )
                conn.execute(
                    "INSERT INTO passage_fts (passage_id, chapter_no, chapter_file, text, entities, events, locations)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (pid, no, path.name, tokens_joined, ent_toks, evt_toks, loc_toks),
                )
            conn.execute(
                "INSERT OR REPLACE INTO fts_chapters"
                " (chapter_file, chapter_no, mtime, summary, entities, events, locations, conflict_level)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (path.name, no, mtime, flat[:260],
                 json.dumps(entities, ensure_ascii=False),
                 json.dumps(events, ensure_ascii=False),
                 json.dumps(locations, ensure_ascii=False),
                 conflict_level),
            )
            rebuilt += 1

        # 清理已被删除章节的残留片段
        if current_files:
            placeholders = ",".join("?" * len(current_files))
            conn.execute(
                f"DELETE FROM passages WHERE chapter_file NOT IN ({placeholders})",
                tuple(current_files),
            )
            conn.execute(
                f"DELETE FROM passage_fts WHERE chapter_file NOT IN ({placeholders})",
                tuple(current_files),
            )
        else:
            conn.execute("DELETE FROM passages WHERE 1=1")
            conn.execute("DELETE FROM passage_fts WHERE 1=1")
        conn.execute(
            "INSERT OR REPLACE INTO fts_meta (key, value) VALUES ('character_sig', ?)",
            (character_sig,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO fts_meta (key, value) VALUES ('generated_at', ?)",
            (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "cmd": "build",
        "engine": ENGINE_FTS5,
        "chapter_count": len(chapters),
        "reused_docs": reused,
        "rebuilt_docs": rebuilt,
        "skipped_stubs": skipped_stubs,
        "index_file": str(retrieval_dir / FTS5_DB_FILENAME),
    }


def fts5_index_signature(conn: sqlite3.Connection) -> str:
    """FTS5 索引签名：章节清单(mtime) + 角色签名，驱动查询缓存失效。"""
    rows = conn.execute(
        "SELECT chapter_file, mtime FROM fts_chapters ORDER BY chapter_file"
    ).fetchall()
    raw = "|".join(f"{f}:{m}" for f, m in rows)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    row = conn.execute("SELECT value FROM fts_meta WHERE key='character_sig'").fetchone()
    cs = (str(row[0])[:8] if row else "")
    return f"{len(rows)}-{digest}-cs{cs}"


def fts5_retrieve(
    project_root: Path,
    db_path: Path,
    query_text: str,
    top_k: int,
    candidate_k: int,
    per_chapter: int,
    passage_max_chars: int,
) -> Dict[str, object]:
    """FTS5 检索：BM25 召回候选片段 → 加权启发式精排 → 按章聚合。

    加权规则与 legacy 精排保持一致（实体>事件>词面，近因/冲突加成），
    返回结构完全兼容 legacy retrieve()。
    """
    names = load_character_names(project_root)
    alias_map = load_character_alias_map(project_root)
    # 别名扩展 + 图谱邻接召回（邻居角色所在章节强制进入候选）
    query_entities = _entities_in_text(query_text, names, alias_map)
    query_tokens = tokenize(query_text)

    empty_result = {
        "query": query_text,
        "query_entities": query_entities,
        "retrieved": [],
        "relation_snippets": [],
        "retrieval_stats": {
            "docs_total": 0,
            "candidate_pool": 0,
            "rerank_topk": 0,
            "estimated_context_chars": 0,
            "engine": ENGINE_FTS5,
        },
    }
    if not query_tokens:
        return empty_result

    conn = _fts5_connect(db_path.parent)
    try:
        # OR 召回（任一词命中即进入候选），精度由后续加权启发式重排负责；
        # 若用默认隐式 AND，多 n-gram 同时命中几乎不可能，召回必为空。
        match_q = " OR ".join(f'"{t}"' for t in query_tokens[:48])
        try:
            rows = conn.execute(
                "SELECT passage_id, chapter_no, chapter_file, bm25(passage_fts) AS b"
                " FROM passage_fts WHERE passage_fts MATCH ? ORDER BY b ASC LIMIT ?",
                (match_q, candidate_k * per_chapter * 4),
            ).fetchall()
        except sqlite3.OperationalError:
            return empty_result

        doc_rows = conn.execute(
            "SELECT chapter_no, chapter_file, conflict_level, summary FROM fts_chapters"
        ).fetchall()
        docs_total = len(doc_rows)
        conflict_map = {f: c for _, f, c, _ in doc_rows}
        recency_map = {f: n for n, f, _, _ in doc_rows}
        summary_map = {f: s for _, f, _, s in doc_rows}
        max_no = max(recency_map.values(), default=0) or 1

        # 图谱邻接：实体-章节映射从 passages.entities 重建；邻居章节强制并入候选
        neighbors = _load_graph_neighbors(project_root)
        neighbor_set = {nb for e in query_entities for nb in neighbors.get(e, [])}
        graph_recall_files: List[str] = []
        if neighbor_set:
            ent_rows = conn.execute(
                "SELECT chapter_file, entities FROM passages WHERE entities != ''"
            ).fetchall()
            entity_chapter_map: Dict[str, List[str]] = {}
            for cf, ents_json in ent_rows:
                try:
                    for e in json.loads(ents_json or "[]"):
                        entity_chapter_map.setdefault(str(e), []).append(cf)
                except Exception:
                    continue
            for e in query_entities:
                for nb in neighbors.get(e, []):
                    graph_recall_files.extend(entity_chapter_map.get(nb, []))
            graph_recall_files = list(dict.fromkeys(graph_recall_files))

        # 片段级打分
        passage_scores: Dict[str, List[Tuple[float, str]]] = {}  # chapter_file -> [(score, text)]
        for pid, no, cfile, bm in rows:
            prow = conn.execute(
                "SELECT text, conflict_level FROM passages WHERE passage_id=?", (pid,)
            ).fetchone()
            if not prow:
                continue
            ptext, pconflict = prow
            token_overlap = len(set(query_tokens) & set(tokenize(ptext)))
            entity_overlap = sum(
                1 for e in query_entities
                if any(t and t in ptext for t in (alias_map.get(e) or [e]))
            )
            event_overlap = sum(1 for k in TRIGGER_KEYWORDS if k in ptext and k in query_text)
            recency = (no / max_no)
            conflict_bonus = 0.2 if pconflict in {"high", "medium"} else 0.0
            score = (
                entity_overlap * 3.0
                + event_overlap * 1.8
                + token_overlap * 1.0
                + recency * 0.3
                + conflict_bonus
                + max(0.0, -float(bm)) * 0.05  # BM25 作为弱加成/次序保持
            )
            passage_scores.setdefault(cfile, []).append((score, ptext))

        # 图谱邻居章节强制并入候选（词面可零重叠）
        for cf in graph_recall_files:
            if cf in passage_scores:
                continue
            prow2 = conn.execute(
                "SELECT text FROM passages WHERE chapter_file=? ORDER BY rowid LIMIT ?",
                (cf, per_chapter),
            ).fetchall()
            for (ptext2,) in prow2:
                if ptext2:
                    passage_scores.setdefault(cf, []).append((0.1, ptext2))

        # 按章聚合：章节分 = 该章最高片段分 + 近因/冲突加成 + 图谱邻居加成
        chapter_scores: List[Tuple[float, str]] = []
        for cfile, plist in passage_scores.items():
            best = max(s for s, _ in plist)
            no = recency_map.get(cfile, 0)
            conflict_bonus = 0.2 if conflict_map.get(cfile) in {"high", "medium"} else 0.0
            chapter_entities = [n for n in names if any(n in t for _, t in plist)]
            neighbor_bonus = 0.5 * len(neighbor_set & set(chapter_entities))
            chapter_scores.append(
                (best + (no / max_no) * 0.3 + conflict_bonus + neighbor_bonus, cfile)
            )
        chapter_scores.sort(key=lambda x: x[0], reverse=True)
        picked = chapter_scores[:top_k]

        retrieved = []
        total_chars = 0
        for cscore, cfile in picked:
            plist = sorted(passage_scores.get(cfile, []), key=lambda x: x[0], reverse=True)
            passages_out = []
            for score, ptext in plist[:per_chapter]:
                short = ptext if len(ptext) <= passage_max_chars else ptext[:passage_max_chars].rstrip() + "..."
                passages_out.append({
                    "score": round(score, 3),
                    "reason": {"token_overlap": 0, "entity_overlap": 0},  # 与 legacy 结构对齐
                    "text": short,
                })
                total_chars += len(short)
            chapter_entities = [n for n in names if any(n in t for _, t in plist)]
            retrieved.append({
                "score": round(cscore, 3),
                "reason": {"token_overlap": 0, "entity_overlap": 0, "recency": 0.0},
                "chapter_file": cfile,
                "chapter_path": str(project_root / "03_manuscript" / cfile),
                "summary": str(summary_map.get(cfile, "")),
                "entities": chapter_entities,
                "events": [],
                "locations": [],
                "foreshadow_refs": [],
                "passages": passages_out,
            })

        relation_snippets = extract_relation_snippets(
            project_root / "00_memory" / "character_tracker.md", query_entities
        )
        return {
            "query": query_text,
            "query_entities": query_entities,
            "index_signature": fts5_index_signature(conn),
            "retrieved": retrieved,
            "relation_snippets": relation_snippets,
            "retrieval_stats": {
                "docs_total": docs_total,
                "candidate_pool": len(passage_scores),
                "rerank_topk": len(retrieved),
                "estimated_context_chars": total_chars,
                "engine": ENGINE_FTS5,
            },
        }
    finally:
        conn.close()


def write_context_md(project_root: Path, result: Dict[str, object]) -> Path:
    retrieval_dir = project_root / "00_memory" / "retrieval"
    ensure_dir(retrieval_dir)
    out = retrieval_dir / "next_plot_context.md"

    lines = []
    lines.append("# 新剧情写作上下文建议（RAG）")
    lines.append("")
    lines.append(f"- 查询：{result.get('query', '')}")
    entities = result.get("query_entities", [])
    lines.append(f"- 命中角色：{', '.join(entities) if entities else '无'}")
    if result.get("cache_hit"):
        lines.append("- 缓存命中：是（复用历史检索结果）")
    if result.get("skipped"):
        lines.append(f"- 条件触发：跳过（{'; '.join(result.get('trigger_reason', []))}）")
    stats = result.get("retrieval_stats", {})
    if stats:
        lines.append(
            "- 检索统计：候选池={candidate_pool} / 总文档={docs_total} / 估算上下文字符={estimated_context_chars}".format(
                candidate_pool=stats.get("candidate_pool", 0),
                docs_total=stats.get("docs_total", 0),
                estimated_context_chars=stats.get("estimated_context_chars", 0),
            )
        )
    lines.append("")
    lines.append("## 建议先读（固定）")
    lines.append("- 00_memory/novel_plan.md")
    lines.append("- 00_memory/novel_state.md")
    lines.append("")
    if result.get("skipped"):
        lines.append("## 本次检索策略")
        lines.append("- 判定为轻场景或信息不足，本次跳过章节检索以节省上下文。")
        lines.append("- 如需强制检索，可使用 `--force`。")
        out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return out

    lines.append("## 建议回读章节（Top）")
    retrieved = result.get("retrieved", [])
    if not retrieved:
        lines.append("- 无可用章节")
    else:
        for i, r in enumerate(retrieved, 1):
            lines.append(f"{i}. `{r['chapter_file']}` | score={r['score']} | 命中={r['reason']}")
            lines.append(f"   摘要：{r['summary']}")
            meta_bits = []
            if r.get("events"):
                meta_bits.append("事件=" + ",".join(r["events"][:4]))
            if r.get("locations"):
                meta_bits.append("地点=" + ",".join(r["locations"][:3]))
            if r.get("foreshadow_refs"):
                meta_bits.append("伏笔=" + " / ".join(r["foreshadow_refs"][:2]))
            if meta_bits:
                lines.append("   元数据：" + "；".join(meta_bits))
            passages = r.get("passages", [])
            if passages:
                lines.append("   关键片段：")
                for p in passages:
                    lines.append(f"   - {p['text']} (reason={p['reason']}, score={p['score']})")

    lines.append("")
    lines.append("## 角色关系相关片段")
    snippets = result.get("relation_snippets", [])
    if not snippets:
        lines.append("- 无命中（可补充 character_tracker）")
    else:
        for i, s in enumerate(snippets, 1):
            lines.append(f"### 片段 {i}")
            lines.append("```")
            lines.append(s)
            lines.append("```")

    lines.append("")
    lines.append("## 写作前执行建议")
    lines.append("1. 读取上述 Top 章节，确认人物关系与伏笔状态。")
    lines.append("2. 若发现冲突，先执行 /检查一致性 再写作。")
    lines.append("3. 写作后继续执行门禁链路。")

    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="构建章节索引并按新剧情检索相关章节上下文")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="更新剧情索引")
    p_build.add_argument("--project-root", required=True)
    p_build.add_argument("--keyword-top-n", type=int, default=20)
    p_build.add_argument("--full-rebuild", action="store_true", help="禁用增量索引，强制全量重建")
    p_build.add_argument("--engine", choices=[ENGINE_LEGACY, ENGINE_FTS5, ENGINE_HYBRID], default=ENGINE_LEGACY,
                         help="检索引擎：legacy / fts5 / hybrid（FTS5 + 本地语义向量）")
    p_build.add_argument("--vector-provider", choices=["ollama", "sentence-transformers", "hash"],
                         default=os.environ.get("NOVEL_VECTOR_PROVIDER", "ollama"))
    p_build.add_argument("--vector-model", default=os.environ.get("NOVEL_VECTOR_MODEL", "bge-m3"))
    p_build.add_argument("--ollama-url", default=os.environ.get("NOVEL_VECTOR_OLLAMA_URL", "http://127.0.0.1:11434"))

    p_query = sub.add_parser("query", help="检索新剧情关联章节")
    p_query.add_argument("--project-root", required=True)
    p_query.add_argument("--query", required=True)
    p_query.add_argument("--top-k", type=int, default=4)
    p_query.add_argument("--auto-build", action="store_true")
    p_query.add_argument("--full-rebuild", action="store_true", help="与 --auto-build 联用时强制全量重建")
    p_query.add_argument("--passages-per-chapter", type=int, default=2, help="每章返回片段数量")
    p_query.add_argument("--candidate-k", type=int, default=12, help="粗筛候选池大小（两级检索第一阶段）")
    p_query.add_argument("--passage-max-chars", type=int, default=220, help="单片段最大字符数")
    p_query.add_argument("--conditional", dest="conditional", action="store_true", default=True, help="启用条件触发，轻场景跳过检索")
    p_query.add_argument("--no-conditional", dest="conditional", action="store_false", help="关闭条件触发，每次都检索")
    p_query.add_argument("--force", action="store_true", help="强制检索，忽略条件触发判定")
    p_query.add_argument("--use-cache", dest="use_cache", action="store_true", default=True, help="启用查询缓存")
    p_query.add_argument("--no-cache", dest="use_cache", action="store_false", help="禁用查询缓存")
    p_query.add_argument("--engine", choices=[ENGINE_LEGACY, ENGINE_FTS5, ENGINE_HYBRID], default=ENGINE_LEGACY,
                         help="检索引擎：legacy / fts5 / hybrid（FTS5 + 本地语义向量）")
    p_query.add_argument("--vector-provider", choices=["ollama", "sentence-transformers", "hash"],
                         default=os.environ.get("NOVEL_VECTOR_PROVIDER", "ollama"))
    p_query.add_argument("--vector-model", default=os.environ.get("NOVEL_VECTOR_MODEL", "bge-m3"))
    p_query.add_argument("--ollama-url", default=os.environ.get("NOVEL_VECTOR_OLLAMA_URL", "http://127.0.0.1:11434"))
    p_query.add_argument("--emit-json")

    return p.parse_args()


def _emit_query_payload(args: argparse.Namespace, project_root: Path, payload: Dict[str, object]) -> int:
    if getattr(args, "emit_json", None):
        jp = Path(args.emit_json).expanduser().resolve()
        ensure_dir(jp.parent)
        jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _skipped_result_payload(
    args: argparse.Namespace, project_root: Path, trigger: Dict[str, object]
) -> Tuple[Dict[str, object], Dict[str, object]]:
    """条件触发判定为轻场景时构造 result 与 payload（双引擎共用）。"""
    result = {
        "query": args.query,
        "query_entities": trigger.get("entities", []),
        "skipped": True,
        "cache_hit": False,
        "trigger_reason": trigger.get("reason", []),
        "retrieved": [],
        "relation_snippets": [],
        "retrieval_stats": {},
    }
    md_out = write_context_md(project_root, result)
    payload = {
        "ok": True,
        "cmd": "query",
        "engine": getattr(args, "engine", ENGINE_LEGACY),
        "context_file": str(md_out),
        "result": result,
    }
    return result, payload


def _run_query_legacy(args: argparse.Namespace, project_root: Path) -> int:
    """legacy 引擎查询流：JSON 章级索引 + 启发式加权（行为与历史版本一致）。"""
    retrieval_dir = project_root / "00_memory" / "retrieval"
    index_file = retrieval_dir / "story_index.json"
    if args.auto_build or not index_file.exists():
        index = build_index(project_root, incremental=not args.full_rebuild)
    else:
        index = json.loads(index_file.read_text(encoding="utf-8"))

    names = load_character_names(project_root)
    trigger = analyze_query_trigger(args.query, names, load_character_alias_map(project_root))
    if args.conditional and not args.force and not trigger["should_trigger"]:
        _, payload = _skipped_result_payload(args, project_root, trigger)
        return _emit_query_payload(args, project_root, payload)

    cache_file = retrieval_dir / "query_cache.json"
    idx_sig = index_signature(index)
    cache_key = make_cache_key(
        args.query,
        args.top_k,
        args.passages_per_chapter,
        args.passage_max_chars,
        f"{idx_sig}|cand={args.candidate_k}|engine={ENGINE_LEGACY}",
    )

    if args.use_cache:
        cache = load_cache(cache_file)
        entry = cache.get("entries", {}).get(cache_key)
        entry_valid = False
        if entry and isinstance(entry, dict) and "result" in entry:
            saved_raw = str(entry.get("saved_at", ""))
            try:
                saved_at = dt.datetime.strptime(saved_raw, "%Y-%m-%d %H:%M:%S")
                age_seconds = (dt.datetime.now() - saved_at).total_seconds()
                entry_valid = 0 <= age_seconds <= _retrieval_config.cache_ttl_seconds
            except ValueError:
                entry_valid = False
        if entry_valid:
            result = entry["result"]
            result["cache_hit"] = True
            md_out = write_context_md(project_root, result)
            payload = {
                "ok": True, "cmd": "query", "engine": ENGINE_LEGACY,
                "context_file": str(md_out), "cache_hit": True, "result": result,
            }
            return _emit_query_payload(args, project_root, payload)

    result = retrieve(
        index,
        project_root,
        args.query,
        args.top_k,
        candidate_k=max(args.top_k, args.candidate_k),
        per_chapter=args.passages_per_chapter,
        passage_max_chars=args.passage_max_chars,
    )
    result["cache_hit"] = False
    result["skipped"] = False
    result["trigger_reason"] = trigger.get("reason", [])

    if args.use_cache:
        cache = load_cache(cache_file)
        cache.setdefault("entries", {})
        cache["entries"][cache_key] = {
            "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
        }
        save_cache(cache_file, cache)

    md_out = write_context_md(project_root, result)
    payload = {
        "ok": True, "cmd": "query", "engine": ENGINE_LEGACY,
        "context_file": str(md_out), "cache_hit": False, "result": result,
    }
    return _emit_query_payload(args, project_root, payload)


def _run_query_fts5(args: argparse.Namespace, project_root: Path) -> int:
    """FTS5 引擎查询流：SQLite 片段级索引 + BM25 召回 + 加权重排。"""
    retrieval_dir = project_root / "00_memory" / "retrieval"
    db_file = retrieval_dir / FTS5_DB_FILENAME
    if args.auto_build or not db_file.exists():
        fts5_build_index(
            project_root,
            keyword_top_n=getattr(args, "keyword_top_n", 20),
            incremental=not args.full_rebuild,
        )

    names = load_character_names(project_root)
    trigger = analyze_query_trigger(args.query, names, load_character_alias_map(project_root))
    if args.conditional and not args.force and not trigger["should_trigger"]:
        _, payload = _skipped_result_payload(args, project_root, trigger)
        return _emit_query_payload(args, project_root, payload)

    conn = _fts5_connect(retrieval_dir)
    try:
        idx_sig = fts5_index_signature(conn)
    finally:
        conn.close()
    cache_file = retrieval_dir / "query_cache.json"
    cache_key = make_cache_key(
        args.query,
        args.top_k,
        args.passages_per_chapter,
        args.passage_max_chars,
        f"{idx_sig}|cand={args.candidate_k}|engine={ENGINE_FTS5}",
    )

    if args.use_cache:
        cache = load_cache(cache_file)
        entry = cache.get("entries", {}).get(cache_key)
        entry_valid = False
        if entry and isinstance(entry, dict) and "result" in entry:
            saved_raw = str(entry.get("saved_at", ""))
            try:
                saved_at = dt.datetime.strptime(saved_raw, "%Y-%m-%d %H:%M:%S")
                age_seconds = (dt.datetime.now() - saved_at).total_seconds()
                entry_valid = 0 <= age_seconds <= _retrieval_config.cache_ttl_seconds
            except ValueError:
                entry_valid = False
        if entry_valid:
            result = entry["result"]
            result["cache_hit"] = True
            md_out = write_context_md(project_root, result)
            payload = {
                "ok": True, "cmd": "query", "engine": ENGINE_FTS5,
                "context_file": str(md_out), "cache_hit": True, "result": result,
            }
            return _emit_query_payload(args, project_root, payload)

    result = fts5_retrieve(
        project_root,
        db_file,
        args.query,
        args.top_k,
        candidate_k=max(args.top_k, args.candidate_k),
        per_chapter=args.passages_per_chapter,
        passage_max_chars=args.passage_max_chars,
    )
    result["cache_hit"] = False
    result["skipped"] = False
    result["trigger_reason"] = trigger.get("reason", [])

    if args.use_cache:
        cache = load_cache(cache_file)
        cache.setdefault("entries", {})
        cache["entries"][cache_key] = {
            "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
        }
        save_cache(cache_file, cache)

    md_out = write_context_md(project_root, result)
    payload = {
        "ok": True, "cmd": "query", "engine": ENGINE_FTS5,
        "context_file": str(md_out), "cache_hit": False, "result": result,
    }
    return _emit_query_payload(args, project_root, payload)


def _hybrid_build(args: argparse.Namespace, project_root: Path) -> Dict[str, object]:
    """Build lexical and vector indexes; vector failure degrades explicitly to FTS5."""
    lexical = fts5_build_index(
        project_root,
        keyword_top_n=getattr(args, "keyword_top_n", 20),
        incremental=not args.full_rebuild,
    )
    try:
        from local_vector_retriever import build_index as build_vector_index

        vector = build_vector_index(
            project_root,
            provider=args.vector_provider,
            model=args.vector_model,
            ollama_url=args.ollama_url,
            incremental=not args.full_rebuild,
        )
        degraded = False
        error = ""
    except Exception as exc:
        vector = {"ok": False, "error": str(exc)}
        degraded = True
        error = str(exc)
    return {
        "ok": True,
        "cmd": "build",
        "engine": ENGINE_HYBRID,
        "chapter_count": lexical.get("chapter_count", 0),
        "lexical": lexical,
        "vector": vector,
        "vector_degraded": degraded,
        "degraded_reason": error,
    }


def _rrf_hybrid(lexical: Dict[str, object], vector: Dict[str, object], top_k: int) -> Dict[str, object]:
    """Reciprocal-rank fusion by chapter, retaining the best evidence passages.

    RRF is intentionally the primary signal, but pure rank fusion discards the
    size of an unusually strong lexical match. Add a small, bounded bonus for
    that direct evidence so an exact answer is not buried beneath chapters that
    merely appear in both candidate lists.
    """
    fused: Dict[str, Dict[str, object]] = {}
    lexical_items = lexical.get("retrieved", []) if isinstance(lexical, dict) else []
    vector_items = vector.get("retrieved", []) if isinstance(vector, dict) else []
    lexical_strengths: Dict[str, float] = {}
    for item in lexical_items if isinstance(lexical_items, list) else []:
        if not isinstance(item, dict):
            continue
        chapter_file = str(item.get("chapter_file") or item.get("file") or "")
        if not chapter_file:
            continue
        passage_scores = []
        passages = item.get("passages")
        if isinstance(passages, list):
            for passage in passages:
                if not isinstance(passage, dict):
                    continue
                try:
                    passage_scores.append(max(0.0, float(passage.get("score", 0.0))))
                except (TypeError, ValueError):
                    continue
        try:
            fallback_score = max(0.0, float(item.get("score", 0.0)))
        except (TypeError, ValueError):
            fallback_score = 0.0
        lexical_strengths[chapter_file] = max(passage_scores or [fallback_score])
    lexical_peak = max(lexical_strengths.values(), default=0.0)
    lexical_chapters_seen = set()
    for rank, item in enumerate(lexical_items if isinstance(lexical_items, list) else [], 1):
        if not isinstance(item, dict):
            continue
        chapter_file = str(item.get("chapter_file") or item.get("file") or "")
        if not chapter_file:
            continue
        row = fused.setdefault(chapter_file, {"chapter_file": chapter_file, "score": 0.0, "passages": [], "sources": []})
        if chapter_file not in lexical_chapters_seen:
            row["score"] = float(row["score"]) + 1.0 / (60 + rank)
            row["sources"].append("fts5")
            lexical_chapters_seen.add(chapter_file)
        row["chapter_no"] = item.get("chapter_no") or item.get("chapter")
        row["chapter_path"] = item.get("chapter_path") or item.get("path")
        row["summary"] = item.get("summary", "")
        row["events"] = item.get("events", [])
        row["locations"] = item.get("locations", [])
        row["foreshadow_refs"] = item.get("foreshadow_refs", [])
        row["_lexical_evidence"] = lexical_strengths.get(chapter_file, 0.0)
        passages = item.get("passages")
        if isinstance(passages, list):
            row["passages"].extend(passages[:2])
        elif item.get("text"):
            row["passages"].append({"text": item.get("text"), "score": item.get("score")})
    vector_chapters_seen = set()
    for rank, item in enumerate(vector_items if isinstance(vector_items, list) else [], 1):
        if not isinstance(item, dict):
            continue
        chapter_file = str(item.get("chapter_file") or "")
        if not chapter_file:
            continue
        row = fused.setdefault(chapter_file, {"chapter_file": chapter_file, "score": 0.0, "passages": [], "sources": []})
        if chapter_file not in vector_chapters_seen:
            row["score"] = float(row["score"]) + 1.0 / (60 + rank)
            row["sources"].append("vector")
            vector_chapters_seen.add(chapter_file)
        row["chapter_no"] = item.get("chapter_no")
        row["chapter_path"] = item.get("chapter_path")
        row.setdefault("summary", str(item.get("text", ""))[:180])
        row.setdefault("events", [])
        row.setdefault("locations", [])
        row.setdefault("foreshadow_refs", [])
        row["passages"].append({
            "text": item.get("text", ""),
            "score": item.get("score", 0.0),
            "reason": "local_semantic_vector",
        })
    for row in fused.values():
        rrf_score = float(row["score"])
        lexical_evidence = float(row.pop("_lexical_evidence", 0.0))
        normalized_evidence = lexical_evidence / lexical_peak if lexical_peak > 0.0 else 0.0
        lexical_bonus = min(0.02, max(0.0, normalized_evidence) * 0.02)
        row["score"] = rrf_score + lexical_bonus
        row["fusion"] = {
            "rrf_score": round(rrf_score, 6),
            "lexical_evidence": round(lexical_evidence, 6),
            "lexical_evidence_bonus": round(lexical_bonus, 6),
        }
    all_ranked = sorted(fused.values(), key=lambda row: float(row["score"]), reverse=True)
    ranked = all_ranked[: max(1, top_k)]
    semantic_only_reserved = False
    if top_k >= 3 and ranked and not any(row.get("sources") == ["vector"] for row in ranked):
        semantic_only = next((row for row in all_ranked if row.get("sources") == ["vector"]), None)
        if semantic_only is not None and semantic_only not in ranked:
            ranked[-1] = semantic_only
            semantic_only_reserved = True
    for row in ranked:
        row["score"] = round(float(row["score"]), 6)
        row["sources"] = list(dict.fromkeys(row["sources"]))
        row["reason"] = "hybrid_rrf:" + "+".join(row["sources"])
        row.setdefault("summary", "")
        row.setdefault("events", [])
        row.setdefault("locations", [])
        row.setdefault("foreshadow_refs", [])
        seen = set()
        unique = []
        for passage in row["passages"]:
            key = str(passage.get("text", ""))
            if key and key not in seen:
                unique.append(passage)
                seen.add(key)
        row["passages"] = unique[:3]
    return {
        "query": lexical.get("query") or vector.get("query"),
        "query_entities": lexical.get("query_entities", []),
        "retrieved": ranked,
        "relation_snippets": lexical.get("relation_snippets", []),
        "retrieval_stats": {
            "engine": ENGINE_HYBRID,
            "lexical_returned": len(lexical_items) if isinstance(lexical_items, list) else 0,
            "vector_returned": len(vector_items) if isinstance(vector_items, list) else 0,
            "lexical_chapters_fused": len(lexical_chapters_seen),
            "vector_chapters_fused": len(vector_chapters_seen),
            "rerank_topk": len(ranked),
            "direct_lexical_evidence_bonus": True,
            "semantic_only_slot_reserved": semantic_only_reserved,
            "estimated_context_chars": sum(
                len(str(p.get("text", ""))) for row in ranked for p in row.get("passages", [])
            ),
        },
    }


def _run_query_hybrid(args: argparse.Namespace, project_root: Path) -> int:
    retrieval_dir = project_root / "00_memory" / "retrieval"
    if args.auto_build or not (retrieval_dir / FTS5_DB_FILENAME).exists():
        _hybrid_build(args, project_root)

    names = load_character_names(project_root)
    trigger = analyze_query_trigger(args.query, names, load_character_alias_map(project_root))
    if args.conditional and not args.force and not trigger["should_trigger"]:
        _, payload = _skipped_result_payload(args, project_root, trigger)
        return _emit_query_payload(args, project_root, payload)

    lexical = fts5_retrieve(
        project_root,
        retrieval_dir / FTS5_DB_FILENAME,
        args.query,
        max(args.top_k, args.candidate_k),
        candidate_k=max(args.top_k, args.candidate_k),
        per_chapter=args.passages_per_chapter,
        passage_max_chars=args.passage_max_chars,
    )
    vector_degraded = False
    vector_error = ""
    try:
        from local_vector_retriever import DB_FILENAME, build_index as build_vector_index, query_index

        if args.auto_build or not (retrieval_dir / DB_FILENAME).exists():
            build_vector_index(
                project_root,
                provider=args.vector_provider,
                model=args.vector_model,
                ollama_url=args.ollama_url,
                incremental=not args.full_rebuild,
            )
        vector = query_index(
            project_root,
            args.query,
            top_k=max(args.top_k, args.candidate_k),
            provider=args.vector_provider,
            model=args.vector_model,
            ollama_url=args.ollama_url,
        )
    except Exception as exc:
        vector = {"ok": False, "retrieved": [], "error": str(exc)}
        vector_degraded = True
        vector_error = str(exc)

    result = _rrf_hybrid(lexical, vector, args.top_k)
    result["cache_hit"] = False
    result["skipped"] = False
    result["trigger_reason"] = trigger.get("reason", [])
    result["vector_degraded"] = vector_degraded
    result["degraded_reason"] = vector_error
    md_out = write_context_md(project_root, result)
    payload = {
        "ok": True,
        "cmd": "query",
        "engine": ENGINE_HYBRID,
        "context_file": str(md_out),
        "cache_hit": False,
        "vector_degraded": vector_degraded,
        "result": result,
    }
    return _emit_query_payload(args, project_root, payload)


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()

    if args.cmd == "build":
        if getattr(args, "engine", ENGINE_LEGACY) == ENGINE_HYBRID:
            payload = _hybrid_build(args, project_root)
        elif getattr(args, "engine", ENGINE_LEGACY) == ENGINE_FTS5:
            payload = fts5_build_index(
                project_root,
                keyword_top_n=args.keyword_top_n,
                incremental=not args.full_rebuild,
            )
        else:
            index = build_index(
                project_root,
                keyword_top_n=args.keyword_top_n,
                incremental=not args.full_rebuild,
            )
            payload = {
                "ok": True,
                "cmd": "build",
                "engine": ENGINE_LEGACY,
                "chapter_count": index.get("chapter_count", 0),
                "reused_docs": index.get("reused_docs", 0),
                "rebuilt_docs": index.get("rebuilt_docs", 0),
                "index_file": str(project_root / "00_memory" / "retrieval" / "story_index.json"),
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if getattr(args, "engine", ENGINE_LEGACY) == ENGINE_HYBRID:
        return _run_query_hybrid(args, project_root)
    if getattr(args, "engine", ENGINE_LEGACY) == ENGINE_FTS5:
        return _run_query_fts5(args, project_root)
    return _run_query_legacy(args, project_root)


if __name__ == "__main__":
    raise SystemExit(main())
