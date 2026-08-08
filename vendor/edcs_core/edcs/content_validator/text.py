"""Plain text, logs, and email (.eml/.msg) extraction."""
from __future__ import annotations

import email
import email.policy
from pathlib import Path

from edcs.content_validator.base import ExtractionResult, register

try:
    from charset_normalizer import from_path as sniff
except ImportError:  # pragma: no cover
    sniff = None

try:
    import extract_msg
except ImportError:  # pragma: no cover
    extract_msg = None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        if sniff:
            best = sniff(str(path)).best()
            if best:
                return str(best)
        return path.read_text(encoding="latin-1", errors="replace")


@register(".txt", ".log", ".md", ".csv")
def extract_text(path: Path) -> ExtractionResult:
    res = ExtractionResult()
    try:
        res.text = _read_text(path)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res


@register(".eml")
def extract_eml(path: Path) -> ExtractionResult:
    res = ExtractionResult()
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        res.text = body.get_content() if body else ""
        res.extra["attachments"] = sum(1 for _ in msg.iter_attachments())
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res


@register(".msg")
def extract_msg_file(path: Path) -> ExtractionResult:
    res = ExtractionResult()
    if extract_msg is None:
        res.error = "extract-msg not installed"
        return res
    try:
        m = extract_msg.Message(str(path))
        res.text = (m.body or "").strip()
        res.extra["attachments"] = len(m.attachments)
        m.close()
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res
