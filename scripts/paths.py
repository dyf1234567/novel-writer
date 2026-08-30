"""Portable data-path resolution for Novel Writer.

Skill code is immutable application logic. Mutable author packs, indexes, and
style libraries live in a user data directory or an explicitly configured path.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_home() -> Path:
    configured = os.environ.get("NOVEL_WRITER_DATA_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if base:
            return (Path(base) / "novel-writer").resolve()

    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "novel-writer").resolve()
    return (Path.home() / ".local" / "share" / "novel-writer").resolve()


def author_style_root() -> Path:
    configured = os.environ.get("AUTHOR_STYLE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return data_home() / "authors"


def style_library_root() -> Path:
    configured = os.environ.get("NOVEL_STYLE_LIBRARY_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return data_home() / "style-library"
