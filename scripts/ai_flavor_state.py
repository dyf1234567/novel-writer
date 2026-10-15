"""Content-bound heuristic scan and explicit false-positive review.

The scan is mandatory, but its lexical patterns cannot establish AI authorship.
Markdown reports are display artifacts, never acceptance credentials.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from common import slugify

DETECTOR_VERSION = 1


def scan_chapter(path: Path) -> dict:
    """内容绑定的 AI 痕迹凭据。

    9.0 合并版说明：text_humanizer 词法检测器已移除（v9 主检测器为
    oh-story 的 check-ai-patterns.js，经 storyctl chapter check 收口）。
    此处降级为"扫描不可用"凭据：仍然绑定章节 SHA256（防篡改语义不变），
    severity 记为 unavailable，AI 味判定以 oh 检测器的章收口结果为准。
    """
    raw = path.read_bytes()
    return {
        "schema_version": 1,
        "detector_version": DETECTOR_VERSION,
        "chapter_sha256": hashlib.sha256(raw).hexdigest(),
        "severity": "unavailable",
        "issues": ["v9: text_humanizer removed; use storyctl chapter check (oh detector)"],
        "ai_score": 0,
    }


def review_path(root: Path, chapter: Path) -> Path:
    return root / "04_editing/gate_artifacts" / slugify(chapter.stem) / "ai_flavor_review.json"


def check_chapter(root: Path, chapter: Path) -> dict:
    scan = scan_chapter(chapter)
    scan["reviewed_false_positive"] = False
    if scan["severity"] == "low":
        scan.update(passed=True, message="当前正文已扫描：低风险")
        return scan
    if scan["severity"] == "unavailable":
        # 9.0 合并版：词法扫描器已移除，凭据仅做 SHA256 内容绑定；
        # AI 味判定由 oh 检测器（storyctl chapter check）在章收口承担。
        scan.update(passed=True, message="v9: 词法扫描不可用，凭据仅绑定内容指纹；AI 味以 oh 检测器收口为准")
        return scan
    try:
        review = json.loads(review_path(root, chapter).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        review = None
    valid = (
        isinstance(review, dict) and review.get("schema_version") == 1
        and review.get("verdict") == "false_positive"
        and review.get("scan") == {k: scan[k] for k in (
            "schema_version", "detector_version", "chapter_sha256", "severity", "issues", "ai_score")}
        and isinstance(review.get("reviewer"), str) and bool(review["reviewer"].strip())
        and isinstance(review.get("reason"), str) and len(review["reason"].strip()) >= 10
    )
    scan["reviewed_false_positive"] = bool(valid)
    scan["passed"] = bool(valid)
    scan["message"] = (
        "当前正文已扫描，命中项已按本章内容完成误报复核"
        if valid else
        "AI 风格扫描命中待复核项；请润色后重检，或用 text_humanizer.py review "
        "逐项审阅并说明保留理由。正文或检测器变化后旧复核失效。"
    )
    return scan


def record_false_positive(root: Path, chapter: Path, reviewer: str, reason: str) -> dict:
    from canonical_state import atomic_json, chapter_path

    chapter = chapter_path(root, chapter)
    if not reviewer.strip() or len(reason.strip()) < 10:
        raise ValueError("误报复核需要审阅者和具体保留理由（至少 10 个字符）")
    scan = scan_chapter(chapter)
    if scan["severity"] == "low":
        raise ValueError("当前正文为低风险，无需误报豁免")
    record = {"schema_version": 1, "verdict": "false_positive", "scan": scan,
              "reviewer": reviewer.strip(), "reason": reason.strip()}
    if hashlib.sha256(chapter.read_bytes()).hexdigest() != scan["chapter_sha256"]:
        raise ValueError("复核期间正文已改变，请重新审阅")
    atomic_json(review_path(root, chapter), record)
    return record
