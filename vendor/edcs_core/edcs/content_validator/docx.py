from __future__ import annotations

from pathlib import Path

from edcs.content_validator.base import ExtractionResult, register
from edcs.content_validator.corruption import is_encrypted_office

try:
    import docx  # python-docx
except ImportError:  # pragma: no cover
    docx = None


@register(".docx", ".dotx")
def extract_docx(path: Path) -> ExtractionResult:
    res = ExtractionResult()
    if is_encrypted_office(path):
        res.protected = True
        return res
    if docx is None:
        res.error = "python-docx not installed"
        return res
    try:
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for table in d.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        parts.append(cell.text)
        res.text = "\n".join(parts)
        res.extra["paragraphs"] = len(parts)
        res.extra["inline_shapes"] = len(d.inline_shapes)
        # heading-only heuristic: exactly one heading and nothing else
        headings = [p for p in d.paragraphs
                    if p.style.name.lower().startswith("heading") and p.text.strip()]
        body = [p for p in d.paragraphs
                if not p.style.name.lower().startswith("heading") and p.text.strip()]
        res.extra["title_page_only"] = bool(headings) and not body and not d.tables
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res
