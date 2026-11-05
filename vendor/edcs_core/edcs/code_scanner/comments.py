"""Shared helper: decide whether a source line is a (fully) commented-out line.

Scanners should not flag IPs / secrets that live in commented-out code — a
comment is not live configuration or a committed credential. We only treat a
line as a comment when the comment marker starts the line (ignoring leading
whitespace). Trailing/inline comments are intentionally NOT skipped, because a
real secret can sit in code before an inline comment on the same line.

This is deliberately language-agnostic and conservative: it recognises the
common single-line comment markers across the file types this scanner walks
(Python/shell/YAML `#`, C/Java/JS/Go `//`, SQL/Lua `--`, and the leading `*`
of a C-style block comment continuation).
"""
from __future__ import annotations

import re

# Leading tokens that mark a whole-line comment across supported languages.
# NOTE: SQL/Lua `--` is handled separately so that long dashed banners such as
# `-----BEGIN RSA PRIVATE KEY-----` (a run of dashes, not a comment) are NOT
# mistaken for comments.
_LINE_COMMENT_PREFIXES = ("#", "//", ";", "*", "<!--")

# Python entry-point guard: `if __name__ == "__main__":` (any quote/spacing).
# The code under it is a demo / manual test-run harness, not shipped runtime
# config, so sample IPs / secrets there should not be treated as findings.
_MAIN_GUARD = re.compile(r'''^\s*if\s+__name__\s*==\s*['"]__main__['"]\s*:''')


def is_comment_line(line: str) -> bool:
    """True if ``line`` is entirely a comment (leading marker only).

    Inline/trailing comments (code followed by a comment) return False so that
    secrets preceding an inline comment are still detected.
    """
    stripped = line.lstrip()
    if not stripped:
        return False
    if stripped.startswith(_LINE_COMMENT_PREFIXES):
        return True
    # SQL/Lua `--` comment, but only a genuine `--` marker: a third dash means
    # this is a dashed separator/banner (e.g. a PEM key header), not a comment.
    if stripped.startswith("--") and not stripped.startswith("---"):
        return True
    return False


def main_guard_lineno(lines: list[str]) -> int | None:
    """1-based line number of a Python ``if __name__ == "__main__":`` guard.

    Everything from that line onward is a manual/demo run harness used to
    dry-run the module; callers skip those lines so sample IPs/secrets in the
    harness are not flagged. Returns ``None`` when there is no such guard.
    Only the guard itself is matched; it is almost always a top-level (column
    0) statement, which is what we require to avoid matching it inside strings.
    """
    for i, line in enumerate(lines, start=1):
        if line[:1] not in (" ", "\t") and _MAIN_GUARD.match(line):
            return i
    return None
