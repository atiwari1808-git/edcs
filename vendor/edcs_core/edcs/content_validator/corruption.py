"""Corruption / protection / type-mismatch detection, ordered cheapest-first."""
from __future__ import annotations

import zipfile
from pathlib import Path

try:
    import magic  # python-magic (libmagic)
except ImportError:  # pragma: no cover
    magic = None

try:
    import msoffcrypto
except ImportError:  # pragma: no cover
    msoffcrypto = None

OOXML_EXT = {".docx", ".dotx", ".pptx", ".potx", ".xlsx", ".xlsm", ".xltx"}
ZIP_BOMB_RATIO = 50
ZIP_BOMB_ABS = 1 * 1024 * 1024 * 1024  # 1 GB uncompressed


def magic_mismatch(path: Path) -> str | None:
    """Returns a reason string when magic bytes disagree with the extension."""
    head = path.open("rb").read(8)
    ext = path.suffix.lower()
    if ext == ".pdf" and not head.startswith(b"%PDF-"):
        return "File has .pdf extension but is not a PDF (magic bytes mismatch)"
    if ext in OOXML_EXT and not (head.startswith(b"PK\x03\x04")
                                 or head.startswith(b"\xd0\xcf\x11\xe0")):
        return f"File has {ext} extension but is neither OOXML zip nor OLE container"
    if magic is not None:
        try:
            mime = magic.from_file(str(path), mime=True)
            if ext == ".pdf" and mime != "application/pdf":
                return f"libmagic reports {mime} for a .pdf file"
        except Exception:
            pass
    return None


def zip_integrity(path: Path) -> str | None:
    """OOXML integrity + zip-bomb guard. Returns reason string on failure."""
    if path.suffix.lower() not in OOXML_EXT:
        return None
    if path.open("rb").read(4) == b"\xd0\xcf\x11\xe0":
        return None  # OLE container (probably encrypted) - handled elsewhere
    try:
        with zipfile.ZipFile(path) as zf:
            total_unc = sum(i.file_size for i in zf.infolist())
            total_cmp = max(1, sum(i.compress_size for i in zf.infolist()))
            if total_unc > ZIP_BOMB_ABS or total_unc / total_cmp > ZIP_BOMB_RATIO:
                return "Archive expansion ratio suspicious (possible zip bomb)"
            bad = zf.testzip()
            if bad:
                return f"Zip integrity failure at member: {bad}"
    except zipfile.BadZipFile:
        return "OOXML container is not a valid zip (corrupt)"
    except Exception as e:
        return f"Zip check failed: {type(e).__name__}"
    return None


def is_encrypted_office(path: Path) -> bool:
    if path.suffix.lower() not in OOXML_EXT or msoffcrypto is None:
        return False
    try:
        with open(path, "rb") as fh:
            return msoffcrypto.OfficeFile(fh).is_encrypted()
    except Exception:
        return False
