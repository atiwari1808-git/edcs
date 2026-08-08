from __future__ import annotations

from pathlib import Path

from edcs.content_validator.base import ExtractionResult, register
from edcs.content_validator.corruption import is_encrypted_office

try:
    from pptx import Presentation
except ImportError:  # pragma: no cover
    Presentation = None


@register(".pptx", ".potx")
def extract_pptx(path: Path) -> ExtractionResult:
    res = ExtractionResult()
    if is_encrypted_office(path):
        res.protected = True
        return res
    if Presentation is None:
        res.error = "python-pptx not installed"
        return res
    try:
        prs = Presentation(path)
        res.page_count = len(prs.slides)
        parts, beyond_first = [], 0
        for i, slide in enumerate(prs.slides):
            slide_text = " ".join(
                sh.text_frame.text for sh in slide.shapes
                if sh.has_text_frame and sh.text_frame.text.strip()
            ).strip()
            if slide_text:
                parts.append(slide_text)
                if i > 0:
                    beyond_first += len(slide_text)
        res.text = "\n".join(parts)
        res.extra["chars_beyond_first_slide"] = beyond_first
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res
