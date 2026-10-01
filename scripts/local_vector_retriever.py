#!/usr/bin/env python3
"""Local semantic passage index for long-form fiction.

The index is deliberately local-only. Embeddings can be produced by a local
Ollama server or an installed sentence-transformers model. A deterministic
hash provider exists for offline tests; it is not a semantic substitute.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from common import ensure_dir, read_text
from canonical_state import accepted_files, begin_index, mark_index, require_current_index
from plot_rag_retriever import (
    _BEAT_SHEET_STUB,
    _NOVEL_FLOW_STUB,
    parse_chapter_no,
    split_passages_with_offsets,
)


DB_FILENAME = "story_vectors.sqlite"
DEFAULT_PROVIDER = os.environ.get("NOVEL_VECTOR_PROVIDER", "ollama")
DEFAULT_MODEL = os.environ.get("NOVEL_VECTOR_MODEL", "bge-m3")
DEFAULT_OLLAMA_URL = os.environ.get("NOVEL_VECTOR_OLLAMA_URL", "http://127.0.0.1:11434")


def _normalize(vector: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    if norm <= 0:
        raise ValueError("embedding returned a zero vector")
    return [float(v) / norm for v in vector]


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes, dim: int) -> Tuple[float, ...]:
    return struct.unpack(f"<{dim}f", blob)


def _hash_embed(texts: Sequence[str], dim: int = 384) -> List[List[float]]:
    """Feature-hash vectors for deterministic tests, not semantic production use."""
    output: List[List[float]] = []
    for text in texts:
        vec = [0.0] * dim
        compact = "".join(text.split())
        grams = [compact[i : i + 3] for i in range(max(1, len(compact) - 2))]
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "little")
            idx = raw % dim
            vec[idx] += -1.0 if raw & 1 else 1.0
        output.append(_normalize(vec))
    return output


def _ollama_embed(texts: Sequence[str], model: str, base_url: str) -> List[List[float]]:
    url = base_url.rstrip("/") + "/api/embed"
    body = json.dumps({"model": model, "input": list(texts)}).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("Ollama /api/embed returned an unexpected payload")
        return [_normalize(v) for v in vectors]
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"local Ollama embedding failed: {exc}") from exc


def _sentence_transformers_embed(texts: Sequence[str], model: str) -> List[List[float]]:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed; use Ollama or install it in the selected Python environment"
        ) from exc
    device = os.environ.get("NOVEL_VECTOR_DEVICE") or None
    encoder = SentenceTransformer(model, device=device)
    vectors = encoder.encode(
        list(texts), normalize_embeddings=True, show_progress_bar=False, batch_size=16
    )
    return [[float(v) for v in row] for row in vectors]


def embed_texts(
    texts: Sequence[str], provider: str, model: str, ollama_url: str
) -> List[List[float]]:
    if provider == "ollama":
        return _ollama_embed(texts, model, ollama_url)
    if provider == "sentence-transformers":
        return _sentence_transformers_embed(texts, model)
    if provider == "hash":
        return _hash_embed(texts)
    raise ValueError(f"unsupported vector provider: {provider}")


def _connect(project_root: Path) -> sqlite3.Connection:
    retrieval_dir = project_root / "00_memory" / "retrieval"
    ensure_dir(retrieval_dir)
    conn = sqlite3.connect(str(retrieval_dir / DB_FILENAME))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS vector_meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS vector_chapters(
            chapter_file TEXT PRIMARY KEY,
            chapter_no INTEGER,
            mtime REAL,
            provider TEXT,
            model TEXT
        );
        CREATE TABLE IF NOT EXISTS vector_passages(
            passage_id TEXT PRIMARY KEY,
            chapter_no INTEGER,
            chapter_file TEXT,
            chapter_path TEXT,
            start_char INTEGER,
            end_char INTEGER,
            text TEXT,
            embedding BLOB,
            dim INTEGER,
            mtime REAL
        );
        CREATE INDEX IF NOT EXISTS idx_vector_chapter ON vector_passages(chapter_no);
        CREATE INDEX IF NOT EXISTS idx_vector_file ON vector_passages(chapter_file);
        """
    )
    return conn


def build_index(
    project_root: Path,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    incremental: bool = True,
    batch_size: int = 16,
) -> Dict[str, object]:
    manuscript_dir = project_root / "03_manuscript"
    canonical_sig, incremental = begin_index(project_root, "vector", incremental)
    chapters, acceptance_warnings = accepted_files(project_root)
    conn = _connect(project_root)
    rebuilt = reused = passage_count = 0
    skipped = len(acceptance_warnings)
    current_files: set[str] = set()
    try:
        for chapter in chapters:
            chapter_no = parse_chapter_no(chapter.name)
            if chapter_no <= 0:
                skipped += 1
                continue
            text = read_text(chapter)
            if _NOVEL_FLOW_STUB in text or _BEAT_SHEET_STUB in text:
                skipped += 1
                continue
            current_files.add(chapter.name)
            mtime = chapter.stat().st_mtime
            row = conn.execute(
                "SELECT mtime, provider, model FROM vector_chapters WHERE chapter_file=?",
                (chapter.name,),
            ).fetchone()
            if (
                incremental
                and row
                and abs(float(row[0]) - mtime) < 1e-6
                and row[1] == provider
                and row[2] == model
            ):
                reused += 1
                passage_count += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM vector_passages WHERE chapter_file=?", (chapter.name,)
                    ).fetchone()[0]
                )
                continue

            passages = split_passages_with_offsets(text)
            conn.execute("DELETE FROM vector_passages WHERE chapter_file=?", (chapter.name,))
            for offset in range(0, len(passages), max(1, batch_size)):
                batch = passages[offset : offset + max(1, batch_size)]
                vectors = embed_texts([p[2] for p in batch], provider, model, ollama_url)
                for local_idx, ((start, end, passage), vector) in enumerate(zip(batch, vectors), 1):
                    idx = offset + local_idx
                    pid = f"ch{chapter_no:04d}-p{idx:03d}"
                    conn.execute(
                        "INSERT OR REPLACE INTO vector_passages VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            pid,
                            chapter_no,
                            chapter.name,
                            str(chapter),
                            start,
                            end,
                            passage,
                            _pack(vector),
                            len(vector),
                            mtime,
                        ),
                    )
                    passage_count += 1
            conn.execute(
                "INSERT OR REPLACE INTO vector_chapters VALUES (?,?,?,?,?)",
                (chapter.name, chapter_no, mtime, provider, model),
            )
            rebuilt += 1

        stored_files = {r[0] for r in conn.execute("SELECT chapter_file FROM vector_chapters")}
        for stale in stored_files - current_files:
            conn.execute("DELETE FROM vector_passages WHERE chapter_file=?", (stale,))
            conn.execute("DELETE FROM vector_chapters WHERE chapter_file=?", (stale,))
        conn.execute("INSERT OR REPLACE INTO vector_meta VALUES ('provider', ?)", (provider,))
        conn.execute("INSERT OR REPLACE INTO vector_meta VALUES ('model', ?)", (model,))
        conn.commit()
    finally:
        conn.close()
    mark_index(project_root, "vector", canonical_sig)
    return {
        "ok": True,
        "engine": "vector",
        "acceptance_warnings": acceptance_warnings,
        "provider": provider,
        "model": model,
        "chapter_count": len(current_files),
        "passage_count": passage_count,
        "rebuilt_docs": rebuilt,
        "reused_docs": reused,
        "skipped_stubs": skipped,
        "index_file": str(project_root / "00_memory" / "retrieval" / DB_FILENAME),
        "semantic": provider != "hash",
    }


def query_index(
    project_root: Path,
    query: str,
    top_k: int = 8,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
) -> Dict[str, object]:
    require_current_index(project_root, "vector")
    conn = _connect(project_root)
    try:
        stored = dict(conn.execute("SELECT key, value FROM vector_meta").fetchall())
        if stored.get("provider") != provider or stored.get("model") != model:
            raise RuntimeError("vector index provider/model mismatch; rebuild the vector index")
        qvec = embed_texts([query], provider, model, ollama_url)[0]
        scored: List[Tuple[float, tuple]] = []
        for row in conn.execute(
            "SELECT passage_id, chapter_no, chapter_file, chapter_path, start_char, end_char, text, embedding, dim FROM vector_passages"
        ):
            vector = _unpack(row[7], int(row[8]))
            if len(vector) != len(qvec):
                continue
            score = sum(a * b for a, b in zip(qvec, vector))
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        retrieved = []
        for score, row in scored[: max(1, top_k)]:
            retrieved.append(
                {
                    "passage_id": row[0],
                    "chapter_no": row[1],
                    "chapter_file": row[2],
                    "chapter_path": row[3],
                    "start_char": row[4],
                    "end_char": row[5],
                    "text": row[6],
                    "score": round(float(score), 6),
                }
            )
        return {
            "ok": True,
            "engine": "vector",
            "provider": provider,
            "model": model,
            "semantic": provider != "hash",
            "query": query,
            "retrieved": retrieved,
            "retrieval_stats": {"passages_total": len(scored), "returned": len(retrieved)},
        }
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地小说语义向量索引")
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build")
    build.add_argument("--project-root", required=True)
    build.add_argument("--provider", choices=["ollama", "sentence-transformers", "hash"], default=DEFAULT_PROVIDER)
    build.add_argument("--model", default=DEFAULT_MODEL)
    build.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    build.add_argument("--batch-size", type=int, default=16)
    build.add_argument("--full-rebuild", action="store_true")
    query = sub.add_parser("query")
    query.add_argument("--project-root", required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--top-k", type=int, default=8)
    query.add_argument("--provider", choices=["ollama", "sentence-transformers", "hash"], default=DEFAULT_PROVIDER)
    query.add_argument("--model", default=DEFAULT_MODEL)
    query.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    try:
        if args.cmd == "build":
            payload = build_index(
                root,
                provider=args.provider,
                model=args.model,
                ollama_url=args.ollama_url,
                incremental=not args.full_rebuild,
                batch_size=args.batch_size,
            )
        else:
            payload = query_index(
                root,
                args.query,
                top_k=args.top_k,
                provider=args.provider,
                model=args.model,
                ollama_url=args.ollama_url,
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "engine": "vector", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

