"""Content-bound chapter acceptance shared by all retrieval entry points.

No implicit adoption: old projects need an explicit, chapter-by-chapter review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from common import chapter_no_from_name, slugify


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def chapter_path(root: Path, value: Path) -> Path:
    root = root.resolve()
    path = (root / value).resolve() if not value.is_absolute() else value.resolve()
    if path.parent != (root / "03_manuscript").resolve() or path.suffix.lower() != ".md":
        raise ValueError("章节必须是项目 03_manuscript 内的 Markdown 文件")
    if chapter_no_from_name(path.name) <= 0:
        raise ValueError("无法识别章节号")
    return path


def _receipt(root: Path, path: Path) -> Path:
    return root / ".flow" / "accepted_chapters" / f"{chapter_no_from_name(path.name):06d}.json"


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"记录格式错误: {path}")
    return data


def blocked_text(text: str) -> bool:
    return ("NOVEL_FLOW_STUB" in text or "BEAT_SHEET_STUB" in text
            or any(s != "completed" for s in re.findall(r"NOVEL_DRAFT_STATUS:\s*([\w-]+)", text)))


def acceptance(root: Path, path: Path) -> tuple[bool, str]:
    try:
        path = chapter_path(root, path)
        if blocked_text(path.read_text(encoding="utf-8-sig")):
            return False, "占位或模板稿"
        receipt = _receipt(root, path)
        if not receipt.exists():
            return False, "未接受；请审阅后使用 canonical_state.py accept"
        record = _read(receipt)
        if record.get("schema_version") != 1 or record.get("file") != path.name:
            return False, "接受记录版本或文件不匹配"
        if record.get("sha256") != digest(path):
            return False, "接受后正文已修改；需重新审阅并接受"
        return True, "accepted"
    except (OSError, ValueError, UnicodeError) as exc:
        return False, f"接受状态不可用: {exc}"


def accept_chapter(root: Path, path: Path, reviewer: str, source: str = "manual") -> dict:
    path = chapter_path(root, path)
    if not reviewer.strip() or source not in {"manual", "pipeline"}:
        raise ValueError("必须提供审阅者及有效接受来源")
    if blocked_text(path.read_text(encoding="utf-8-sig")):
        raise ValueError("拒绝接受占位或模板稿；先完成正文")
    sha = digest(path)
    gate = root / "04_editing" / "gate_artifacts" / slugify(path.stem) / "gate_result.json"
    if source == "pipeline" or gate.exists():
        result = _read(gate)
        if result.get("passed") is not True or result.get("chapter_sha256") != sha:
            raise ValueError("门禁未通过或证据已过期；请对当前正文重新运行门禁")
    receipt = _receipt(root, path)
    if receipt.exists() and _read(receipt).get("file") != path.name:
        raise ValueError("该章号已由其他文件接受；请在原文件上修订，不能双份收编")
    record = {"schema_version": 1, "file": path.name, "sha256": sha,
              "reviewer": reviewer.strip(), "source": source}
    atomic_json(receipt, record)
    return record


def accepted_files(root: Path) -> tuple[list[Path], list[str]]:
    accepted, warnings = [], []
    for path in sorted((root / "03_manuscript").glob("*.md")):
        ok, reason = acceptance(root, path)
        if ok:
            accepted.append(path)
        else:
            warnings.append(f"{path.name}: {reason}")
    return accepted, warnings


def signature(root: Path) -> str:
    # Include actual bytes AND acceptance status: edits with preserved mtime,
    # removals, new receipts and manual revocation invalidate old indexes/cache.
    rows = []
    for path in sorted((root / "03_manuscript").glob("*.md")):
        ok, _ = acceptance(root, path)
        rows.append((path.name, digest(path), ok))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def mark_index(root: Path, engine: str, initial_signature: str) -> None:
    if signature(root) != initial_signature:
        raise RuntimeError("建库期间正文或接受状态变化，请重新 build")
    atomic_json(root / "00_memory/retrieval" / f"canonical_{engine}.json",
                {"schema_version": 1, "signature": initial_signature})


def begin_index(root: Path, engine: str, incremental: bool) -> tuple[str, bool]:
    current = signature(root)
    path = root / "00_memory/retrieval" / f"canonical_{engine}.json"
    try:
        reuse = incremental and _read(path).get("signature") == current
    except (OSError, ValueError):
        reuse = False
    atomic_json(path, {"schema_version": 1, "signature": None, "building": True})
    return current, reuse


def require_current_index(root: Path, engine: str) -> None:
    path = root / "00_memory/retrieval" / f"canonical_{engine}.json"
    if not path.exists() or _read(path).get("signature") != signature(root):
        raise RuntimeError(f"{engine} 索引缺少接受凭证或已过期；审阅并接受正文后重新 build")


def main() -> int:
    parser = argparse.ArgumentParser(description="正文接受记录；不自动收编旧稿")
    parser.add_argument("command", choices=["status", "accept"])
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--chapter-file")
    parser.add_argument("--reviewer")
    parser.add_argument("--confirm", choices=["ACCEPT"])
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    try:
        if args.command == "accept":
            if not args.chapter_file or not args.reviewer or args.confirm != "ACCEPT":
                raise ValueError("accept 需要 --chapter-file、--reviewer 和 --confirm ACCEPT")
            record = accept_chapter(root, Path(args.chapter_file), args.reviewer)
            result = {"ok": True, "accepted": record, "next_step": "重新 build 检索索引"}
        else:
            files, warnings = accepted_files(root)
            result = {"ok": True, "accepted": [p.name for p in files], "warnings": warnings}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
