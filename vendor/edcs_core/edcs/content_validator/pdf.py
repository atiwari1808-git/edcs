"""PDF extraction: PyMuPDF primary (fast, damage-tolerant), pdfplumber as
second opinion on ambiguous layouts."""
from __future__ import annotations

from pathlib import Path

from edcs.content_validator.base import ExtractionResult, register

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


@register(".pdf")
def extract_pdf(path: Path) -> ExtractionResult:
    res = ExtractionResult()
    if fitz is None:
        res.error = "PyMuPDF not installed"
        return res
    try:
        doc = fitz.open(path)
        if doc.needs_pass:
            res.protected = True
            return res
        res.page_count = doc.page_count
        parts = []
        for page in doc:
            txt = page.get_text("text").strip()
            imgs = len(page.get_images(full=True))
            if txt:
                res.text_pages += 1
                parts.append(txt)
            elif imgs:
                res.image_only_pages += 1
        res.text = "\n".join(parts)
        doc.close()
    except Exception as e:  # parser exception == corrupt, never a crash
        res.error = f"{type(e).__name__}: {e}"
    return res
