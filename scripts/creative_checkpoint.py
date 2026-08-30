#!/usr/bin/env python3
"""Human creative checkpoints that can block automatic chapter drafting."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from common import ensure_dir, read_text, write_text


STATE_FILENAME = "creative_checkpoints.json"


def _load_anchors(project_root: Path) -> Dict[str, object]:
    path = project_root / "00_memory" / "outline_anchors.json"
    if not path.exists():
        return {}
    try:
        return json.loads(read_text(path))
    except Exception:
        return {}


def _volume_ending_at(project_root: Path, chapter: int) -> Optional[int]:
    for item in _load_anchors(project_root).get("volumes", []):
        try:
            if int(item.get("chapter_range", [0, 0])[1]) == chapter:
                return int(item.get("volume"))
        except (TypeError, ValueError, IndexError):
            continue
    return None


def _state_path(project_root: Path) -> Path:
    path = project_root / ".flow" / STATE_FILENAME
    ensure_dir(path.parent)
    return path


def _load_state(project_root: Path) -> Dict[str, object]:
    path = _state_path(project_root)
    if not path.exists():
        return {"version": 1, "checkpoints": {}}
    try:
        data = json.loads(read_text(path))
        if isinstance(data, dict):
            data.setdefault("checkpoints", {})
            return data
    except Exception:
        pass
    return {"version": 1, "checkpoints": {}}


def _save_state(project_root: Path, data: Dict[str, object]) -> None:
    _state_path(project_root).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def checkpoint_key(completed_chapter: int) -> str:
    return f"after_ch{completed_chapter:04d}"


def evaluate(
    project_root: Path,
    next_chapter: int,
    interval: int = 10,
    require_volume_audit: bool = True,
    create_if_due: bool = True,
) -> Dict[str, object]:
    completed = max(0, next_chapter - 1)
    volume = _volume_ending_at(project_root, completed)
    reasons: List[str] = []
    if interval > 0 and completed > 0 and completed % interval == 0:
        reasons.append(f"每{interval}章人工检查点")
    if volume is not None:
        reasons.append(f"第{volume}卷卷末")
    if not reasons:
        return {"ok": True, "due": False, "next_chapter": next_chapter}

    key = checkpoint_key(completed)
    data = _load_state(project_root)
    checkpoints = data.setdefault("checkpoints", {})
    record = checkpoints.get(key, {}) if isinstance(checkpoints, dict) else {}
    audit_status = "not_required"
    audit_report = None
    if volume is not None and require_volume_audit:
        audit_state = project_root / "04_editing" / "volume_audits" / f"volume_{volume:02d}" / "audit_state.json"
        if audit_state.exists():
            audit = json.loads(read_text(audit_state))
            audit_status = str(audit.get("status") or "pending_review")
            audit_report = audit.get("report")
        else:
            audit_status = "missing"
            if create_if_due:
                try:
                    from volume_audit import collect_audit

                    audit_payload = collect_audit(project_root, volume)
                    audit_record = audit_payload.get("state", {})
                    audit_status = str(audit_record.get("status") or "pending_review")
                    audit_report = audit_record.get("report")
                except Exception as exc:
                    audit_status = "collection_failed"
                    audit_report = str(exc)

    approved = record.get("status") == "approved"
    audit_ok = audit_status in {"not_required", "pass"}
    if approved and audit_ok:
        return {
            "ok": True,
            "due": True,
            "approved": True,
            "key": key,
            "reasons": reasons,
            "volume_audit_status": audit_status,
        }

    checkpoint_dir = project_root / "04_editing" / "creative_checkpoints"
    ensure_dir(checkpoint_dir)
    checkpoint_file = checkpoint_dir / f"{key}.md"
    if create_if_due:
        lines = [
            f"# 人工创作检查点：完成第{completed}章后",
            "",
            f"- 触发原因：{'；'.join(reasons)}",
            f"- 下一目标章节：第{next_chapter}章",
            f"- 全卷审计：{audit_status}",
            "",
            "## 人工必须决定",
            "- [ ] 当前主线仍值得继续，下一阶段目标明确",
            "- [ ] 主角弧线没有停滞、倒退或被配角替代",
            "- [ ] 近期伏笔的埋设与回收节奏符合创作意图",
            "- [ ] 下一阶段允许揭示与禁止揭示的内容已确认",
            "- [ ] 是否需要改纲、删线、合并角色或调整节奏",
            "- [ ] 审阅至少一章原文，而非只看自动摘要",
            "",
            "## 决策记录",
            "通过后使用 `creative_checkpoint.py approve`；需要调整则使用 `reject` 并写明原因。",
        ]
        write_text(checkpoint_file, "\n".join(lines) + "\n")
        if isinstance(checkpoints, dict):
            checkpoints[key] = {
                "status": record.get("status", "pending"),
                "completed_chapter": completed,
                "next_chapter": next_chapter,
                "reasons": reasons,
                "volume": volume,
                "checkpoint_file": str(checkpoint_file),
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            _save_state(project_root, data)
    return {
        "ok": False,
        "due": True,
        "approved": approved,
        "key": key,
        "reasons": reasons,
        "checkpoint_file": str(checkpoint_file),
        "volume": volume,
        "volume_audit_status": audit_status,
        "volume_audit_report": audit_report,
        "next_step": "完成卷审计（如需要），人工检查原文与计划，然后记录 approve 或 reject。",
    }


def decide(project_root: Path, completed_chapter: int, status: str, reviewer: str, notes: str) -> Dict[str, object]:
    key = checkpoint_key(completed_chapter)
    data = _load_state(project_root)
    checkpoints = data.setdefault("checkpoints", {})
    if not isinstance(checkpoints, dict):
        checkpoints = {}
        data["checkpoints"] = checkpoints
    record = checkpoints.get(key, {})
    record.update(
        {
            "status": status,
            "completed_chapter": completed_chapter,
            "reviewer": reviewer.strip() or "human",
            "notes": notes.strip(),
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    checkpoints[key] = record
    _save_state(project_root, data)
    return {"ok": status == "approved", "key": key, "record": record}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="长篇小说人工创作检查点")
    sub = parser.add_subparsers(dest="cmd", required=True)
    status = sub.add_parser("status")
    status.add_argument("--project-root", required=True)
    status.add_argument("--next-chapter", type=int, required=True)
    status.add_argument("--interval", type=int, default=10)
    status.add_argument("--no-volume-audit", action="store_true")
    for action in ("approve", "reject"):
        command = sub.add_parser(action)
        command.add_argument("--project-root", required=True)
        command.add_argument("--after-chapter", type=int, required=True)
        command.add_argument("--reviewer", default="human")
        command.add_argument("--notes", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    if args.cmd == "status":
        payload = evaluate(
            root,
            args.next_chapter,
            interval=args.interval,
            require_volume_audit=not args.no_volume_audit,
        )
    else:
        payload = decide(
            root,
            args.after_chapter,
            "approved" if args.cmd == "approve" else "rejected",
            args.reviewer,
            args.notes,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
