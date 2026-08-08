"""'Meaningful text' heuristics - the judgment call wearing a boolean costume.

Verdicts: OK | BLANK | TITLE_PAGE_ONLY | IMAGE_ONLY | SUSPECT_SMALL
Thresholds are per-document-type (mandatory_documents.yaml min_chars)."""
from __future__ import annotations

import re
from pathlib import Path

from edcs.content_validator.base import ExtractionResult

SIZE_FLOOR = {".pdf": 2048, ".docx": 6144, ".xlsx": 5120, ".pptx": 25600, ".txt": 10}
DEFAULT_MIN_CHARS = 120

_PAGE_NUM = re.compile(r"^\s*(page\s*)?\d+(\s*/\s*\d+)?\s*$", re.I)
_JIRA = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,7}$")


def meaningful_chars(text: str, boilerplate: list[str]) -> int:
    count = 0
    bp = {b.lower() for b in boilerplate}
    for line in text.splitlines():
        s = line.strip()
        if not s or _PAGE_NUM.match(s) or _JIRA.match(s) or s.lower() in bp:
            continue
        count += len(re.sub(r"\W", "", s))
    return count


def verdict(path: Path, size: int, ext: ExtractionResult,
            min_chars: int, boilerplate: list[str]) -> str:
    if size == 0:
        return "BLANK"
    if ext.protected or ext.error:
        return "OK"  # corruption/protection reported separately, not as blank
    chars = meaningful_chars(ext.text, boilerplate)

    if chars == 0 and ext.image_only_pages == 0 and ext.cell_count == 0:
        return "BLANK"
    if ext.page_count and ext.text_pages == 0 and ext.image_only_pages > 0:
        return "IMAGE_ONLY"
    if ext.page_count > 1 and ext.text_pages <= 1 and chars < min_chars:
        return "TITLE_PAGE_ONLY"
    if ext.extra.get("title_page_only"):
        return "TITLE_PAGE_ONLY"
    if path.suffix.lower() in {".pptx", ".potx"} and ext.page_count > 0:
        if ext.extra.get("chars_beyond_first_slide", 0) < 80:
            return "TITLE_PAGE_ONLY"
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xltx"}:
        return "BLANK" if ext.cell_count < 5 else "OK"
    if chars < min_chars:
        return "BLANK"
    floor = SIZE_FLOOR.get(path.suffix.lower(), 0)
    if size < floor and chars < min_chars * 2:
        return "SUSPECT_SMALL"
    return "OK"
