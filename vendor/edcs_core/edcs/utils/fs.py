"""Filesystem safety helpers: temp dirs, path-traversal guards, size checks."""
from __future__ import annotations

import os
import shutil
import stat
import time
from pathlib import Path


def force_rw_then_delete(func, path, exc_info):  # noqa: ARG001
    """shutil.rmtree onerror handler - .git objects are read-only."""
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    func(path)


def is_within(root: Path, candidate: Path) -> bool:
    """Path-traversal / symlink-escape guard."""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def free_mb(path: Path) -> int:
    return shutil.disk_usage(path).free // (1024 * 1024)


def janitor(base: Path, prefix: str = "edcs_", max_age_h: int = 24) -> int:
    """Remove orphaned scan workspaces from crashed jobs. Returns count removed."""
    removed = 0
    cutoff = time.time() - max_age_h * 3600
    if not base.exists():
        return 0
    for entry in base.iterdir():
        if entry.is_dir() and entry.name.startswith(prefix) and entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, onerror=force_rw_then_delete)
            removed += 1
    return removed


def looks_binary(path: Path, sniff: int = 8192) -> bool:
    with open(path, "rb") as fh:
        return b"\x00" in fh.read(sniff)
