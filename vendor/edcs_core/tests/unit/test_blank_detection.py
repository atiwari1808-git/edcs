from pathlib import Path

from edcs.content_validator.base import ExtractionResult
from edcs.content_validator.blank_rules import meaningful_chars, verdict

BOILER = ["ericsson internal", "tbd"]


def test_zero_bytes_is_blank():
    assert verdict(Path("x.pdf"), 0, ExtractionResult(), 120, BOILER) == "BLANK"


def test_boilerplate_only_is_blank():
    ext = ExtractionResult(text="TBD\nEricsson Internal\nABCD-1234\nPage 1", page_count=3)
    assert verdict(Path("x.docx"), 90000, ext, 120, BOILER) == "BLANK"


def test_real_content_ok():
    ext = ExtractionResult(text="This HLD describes the architecture. " * 30,
                           page_count=5, text_pages=5)
    assert verdict(Path("x.pdf"), 90000, ext, 120, BOILER) == "OK"


def test_image_only_pdf():
    ext = ExtractionResult(page_count=4, image_only_pages=4, text_pages=0)
    assert verdict(Path("x.pdf"), 500000, ext, 120, BOILER) == "IMAGE_ONLY"


def test_title_page_only():
    ext = ExtractionResult(text="ABCD-1234 HLD", page_count=6, text_pages=1)
    assert verdict(Path("x.pdf"), 90000, ext, 500, BOILER) == "TITLE_PAGE_ONLY"


def test_meaningful_chars_strips_noise():
    assert meaningful_chars("Page 1\nABCD-1234\n\nTBD", BOILER) == 0
