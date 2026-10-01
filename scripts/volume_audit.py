#!/usr/bin/env python3
"""Create and record a whole-volume continuity audit checkpoint."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from common import ensure_dir, read_text, write_text
from plot_rag_retriever import parse_chapter_no
from canonical_state import acceptance, atomic_json, digest


STATE_FILE = "audit_state.json"


def audit_fingerprint(project_root: Path, start: int, end: int) -> str:
    inputs = []
    for path in sorted((project_root / "03_manuscript").glob("*.md")):
        if start <= parse_chapter_no(path.name) <= end:
            inputs.append((path.name, digest(path), acceptance(project_root, path)[0]))
    for name in ("novel_state.md", "character_tracker.md", "timeline.md", "world_state.md",
                 "foreshadowing_tracker.md", "outline_anchors.json"):
        path = project_root / "00_memory" / name
        inputs.append((name, digest(path) if path.exists() else None))
    policy = project_root / ".novel_policy.json"
    inputs.append(("policy", digest(policy) if policy.exists() else None))
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode("utf-8")).hexdigest()


def _volume_range(project_root: Path, volume: int) -> Tuple[int, int, str]:
    anchors = project_root / "00_memory" / "outline_anchors.json"
    if anchors.exists():
        try:
            data = json.loads(read_text(anchors))
            for item in data.get("volumes", []):
                if int(item.get("volume", 0)) == volume:
                    start, end = item.get("chapter_range", [0, 0])
                    return int(start), int(end), str(item.get("title") or f"第{volume}卷")
        except Exception:
            pass
    raise RuntimeError(f"cannot resolve chapter range for volume {volume}; pass --start and --end")


def _extract_active_foreshadows(text: str) -> List[str]:
    active = False
    hits: List[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            active = any(word in line for word in ("活跃", "紧急", "进行中"))
        elif active and re.match(r"\|\s*F\d+-\d+\s*\|", line):
            hits.append(line.strip())
    return hits


def collect_audit(
    project_root: Path,
    volume: int,
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> Dict[str, object]:
    if start is None or end is None:
        resolved_start, resolved_end, title = _volume_range(project_root, volume)
        start = resolved_start if start is None else start
        end = resolved_end if end is None else end
    else:
        title = f"第{volume}卷"
    if start < 1 or end < start:
        raise ValueError("invalid volume chapter range")

    manuscript = project_root / "03_manuscript"
    input_fingerprint = audit_fingerprint(project_root, start, end)
    all_chapters = [p for p in manuscript.glob("*.md") if start <= parse_chapter_no(p.name) <= end]
    duplicate_numbers = sorted({parse_chapter_no(p.name) for p in all_chapters
                                if sum(parse_chapter_no(q.name) == parse_chapter_no(p.name)
                                       for q in all_chapters) > 1})
    unaccepted = [p.name for p in all_chapters if not acceptance(project_root, p)[0]]
    chapters = {
        parse_chapter_no(p.name): p
        for p in manuscript.glob("*.md")
        if start <= parse_chapter_no(p.name) <= end
    }
    missing = [n for n in range(start, end + 1) if n not in chapters]
    stubs: List[int] = []
    headings: Dict[str, List[int]] = {}
    chapter_evidence: List[Dict[str, object]] = []
    for number, path in sorted(chapters.items()):
        text = read_text(path)
        if "NOVEL_FLOW_STUB" in text or "[待写]" in text:
            stubs.append(number)
        heading = next((line.strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        headings.setdefault(heading, []).append(number)
        compact = re.sub(r"\s+", " ", text).strip()
        chapter_evidence.append(
            {
                "chapter": number,
                "file": path.name,
                "chars": len(re.sub(r"\s+", "", text)),
                "opening": compact[:180],
                "ending": compact[-220:],
            }
        )

    duplicate_headings = {h: ns for h, ns in headings.items() if len(ns) > 1}
    memory_dir = project_root / "00_memory"
    tracker_files = [
        "novel_state.md",
        "character_tracker.md",
        "timeline.md",
        "world_state.md",
        "foreshadowing_tracker.md",
    ]
    missing_trackers = [name for name in tracker_files if not (memory_dir / name).exists()]
    foreshadow_text = read_text(memory_dir / "foreshadowing_tracker.md") if (memory_dir / "foreshadowing_tracker.md").exists() else ""
    active_foreshadows = _extract_active_foreshadows(foreshadow_text)

    audit_dir = project_root / "04_editing" / "volume_audits" / f"volume_{volume:02d}"
    ensure_dir(audit_dir)
    evidence = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "volume": volume,
        "title": title,
        "chapter_range": [start, end],
        "chapters_found": len(chapters),
        "missing_chapters": missing,
        "duplicate_chapter_numbers": duplicate_numbers,
        "unaccepted_chapters": unaccepted,
        "stub_chapters": stubs,
        "duplicate_headings": duplicate_headings,
        "missing_trackers": missing_trackers,
        "active_foreshadows": active_foreshadows,
        "chapter_evidence": chapter_evidence,
    }
    (audit_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    blocking = bool(missing or stubs or missing_trackers or duplicate_numbers or unaccepted)
    lines = [
        f"# 第{volume}卷全卷审计",
        "",
        f"- 章节范围：第{start}—{end}章",
        f"- 已找到章节：{len(chapters)}",
        f"- 自动结构检查：{'阻断' if blocking else '通过'}",
        "- 审计状态：等待人工或模型语义复核",
        "",
        "## 自动发现",
        f"- 缺失章节：{missing or '无'}",
        f"- 占位章节：{stubs or '无'}",
        f"- 重复章号：{duplicate_numbers or '无'}",
        f"- 未接受或已修改正文：{unaccepted or '无'}",
        f"- 缺失状态文件：{missing_trackers or '无'}",
        f"- 重复标题：{duplicate_headings or '无'}",
        f"- 活跃伏笔条目：{len(active_foreshadows)}",
        "",
        "## 必须人工复核",
        "- [ ] 主角与核心配角的动机、能力、关系是否跨卷连续",
        "- [ ] 时间顺序、旅行耗时、年龄与伤病是否自洽",
        "- [ ] 世界规则是否被无解释突破或遗忘",
        "- [ ] 本卷应回收伏笔是否回收，跨卷伏笔是否仍有承载点",
        "- [ ] 卷首承诺、卷中升级与卷末结果是否构成完整因果链",
        "- [ ] 是否存在与正稿冲突的摘要、追踪器或检索派生事实",
        "- [ ] 下一卷不可提前揭示的信息是否仍被保护",
        "",
        "## 结论",
        "使用 `volume_audit.py complete` 记录 pass 或 needs_revision；未记录前不得把本审计视为通过。",
    ]
    report_path = audit_dir / "audit_report.md"
    write_text(report_path, "\n".join(lines) + "\n")
    state = {
        "schema_version": 2,
        "input_fingerprint": input_fingerprint,
        "volume": volume,
        "chapter_range": [start, end],
        "status": "blocked" if blocking else "pending_review",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "report": str(report_path),
    }
    if audit_fingerprint(project_root, start, end) != input_fingerprint:
        raise RuntimeError("收集期间审计输入变化，请重新 collect")
    atomic_json(audit_dir / STATE_FILE, state)
    return {"ok": not blocking, "state": state, "evidence_file": str(audit_dir / "evidence.json")}


def complete_audit(project_root: Path, volume: int, verdict: str, reviewer: str, notes: str) -> Dict[str, object]:
    if verdict not in {"pass", "needs_revision"} or not reviewer.strip() or not notes.strip():
        raise ValueError("需要有效结论、审阅者和审阅说明")
    audit_dir = project_root / "04_editing" / "volume_audits" / f"volume_{volume:02d}"
    state_path = audit_dir / STATE_FILE
    if not state_path.exists():
        raise RuntimeError("audit does not exist; run collect first")
    state = json.loads(read_text(state_path))
    if verdict == "pass":
        if state.get("schema_version") != 2:
            raise RuntimeError("旧审计缺少内容指纹，请重新 collect 后审阅")
        if state.get("status") == "blocked":
            raise RuntimeError("结构审计仍阻断；先修复并重新 collect，不能直接 pass")
        start, end = state["chapter_range"]
        if state.get("input_fingerprint") != audit_fingerprint(project_root, start, end):
            raise RuntimeError("审计证据已过期，请重新 collect 并审阅")
    state.update(
        {
            "status": verdict,
            "reviewer": reviewer.strip() or "human",
            "notes": notes.strip(),
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    atomic_json(state_path, state)
    return {"ok": verdict == "pass", "state": state}


def status(project_root: Path, volume: int) -> Dict[str, object]:
    state_path = project_root / "04_editing" / "volume_audits" / f"volume_{volume:02d}" / STATE_FILE
    if not state_path.exists():
        return {"ok": False, "volume": volume, "status": "missing"}
    state = json.loads(read_text(state_path))
    if state.get("schema_version") != 2:
        return {"ok": False, "state": {**state, "status": "stale"}, "reason": "重新 collect 旧版审计"}
    start, end = state["chapter_range"]
    if state.get("input_fingerprint") != audit_fingerprint(project_root, start, end):
        return {"ok": False, "state": {**state, "status": "stale"}, "reason": "正文或记忆已变化，请重新 collect"}
    return {"ok": state.get("status") == "pass", "state": state}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全卷连续性审计")
    sub = parser.add_subparsers(dest="cmd", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--project-root", required=True)
    collect.add_argument("--volume", type=int, required=True)
    collect.add_argument("--start", type=int)
    collect.add_argument("--end", type=int)
    complete = sub.add_parser("complete")
    complete.add_argument("--project-root", required=True)
    complete.add_argument("--volume", type=int, required=True)
    complete.add_argument("--verdict", choices=["pass", "needs_revision"], required=True)
    complete.add_argument("--reviewer", default="human")
    complete.add_argument("--notes", default="")
    stat = sub.add_parser("status")
    stat.add_argument("--project-root", required=True)
    stat.add_argument("--volume", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    try:
        if args.cmd == "collect":
            payload = collect_audit(root, args.volume, args.start, args.end)
        elif args.cmd == "complete":
            payload = complete_audit(root, args.volume, args.verdict, args.reviewer, args.notes)
        else:
            payload = status(root, args.volume)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

