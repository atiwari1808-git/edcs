"""ERIDOC document scanner adapter — wired to the real EDCS v1.0.1
DocumentScanner (vendor/edcs_core). See README.md "Integration" section.

Mapping from edcs.models.Finding -> our ScanResult buckets:
  DOC_FOLDER_MISSING / DOC_FOLDER_EMPTY / DOC_MISSING  -> missing_documents
  DOC_BLANK / DOC_TITLE_PAGE_ONLY / DOC_IMAGE_ONLY      -> blank_documents
  severity >= HIGH (anything else)                      -> failed_checks
  severity < HIGH                                       -> warnings

ERIDOC Folder Path field (`eridoc_path`) accepts one of:
  1. A real ERIDOC web link with a folder object id (…?locateId=0b004cffd9ad177d)
     -> the scan is pinned to that EXACT folder, bypassing JIRA-name discovery.
  2. A raw 16-char Documentum object id (e.g. 0b004cffd9ad177d) -> same as (1).
  3. A Documentum folder PATH starting with "/" -> scopes name-based discovery.
  4. Blank -> falls back to the JIRA-based lookup, but ONLY when the tool does
     not mark the ERIDOC path as required.

IMPORTANT (fix): a NON-BLANK path that is neither a valid folder id/link nor a
"/"-path is now REJECTED with a clear error instead of silently falling back to
the JIRA-name lookup. When the tool marks the path REQUIRED, a blank path is
also rejected. This prevents a wrong ERIDOC link from being silently ignored.
"""
import logging
import re
import time
from urllib.parse import urlparse, parse_qs

from django.conf import settings as dj

from .base import ScanResult, TransientScannerError

NAME = "ERIDOC"
log = logging.getLogger(__name__)

_MISSING_CATEGORIES = {"DOC_FOLDER_MISSING", "DOC_FOLDER_EMPTY", "DOC_MISSING"}
_BLANK_CATEGORIES = {"DOC_BLANK", "DOC_TITLE_PAGE_ONLY", "DOC_IMAGE_ONLY"}
_FOLDER_LEVEL = {"DOC_FOLDER_MISSING", "DOC_FOLDER_EMPTY"}

# Categories the vendor scanner emits when it has no content validator for a
# file type. We suppress these for accepted archive types (see below).
_UNSUPPORTED_CATEGORIES = {"DOC_UNSUPPORTED", "DOC_NO_VALIDATOR", "DOC_CONTENT_UNVERIFIED"}
# Extensions accepted in ERIDOC even without a dedicated content validator.
_ACCEPTED_ARCHIVE_EXTS = (".zip",)

# Documentum r_object_id: 16 hex chars. Folder objects carry the "0b" type tag.
_OBJ_ID_RE = re.compile(r"^[0-9a-fA-F]{16}$")
_ID_PARAM_KEYS = ("locateId", "objectId", "id", "r_object_id", "folderId")


class EridocPathError(ValueError):
    """Raised when a provided ERIDOC path/link cannot be understood, or a
    required path is blank. Non-retryable — surfaces as a scanner ERROR."""


def _extract_folder_id(value: str):
    """Pull a 16-char Documentum object id out of an ERIDOC link, or accept a
    bare object id. Returns None when the value isn't an id-bearing link."""
    v = (value or "").strip()
    if not v:
        return None
    if _OBJ_ID_RE.match(v):
        return v.lower()
    if "://" not in v and "?" not in v and "=" not in v:
        return None  # not a URL and not an id -> treat as path elsewhere
    try:
        qs = parse_qs(urlparse(v).query)
    except Exception:
        return None
    for key in _ID_PARAM_KEYS:
        for qk, vals in qs.items():
            if qk.lower() == key.lower() and vals:
                cand = vals[0].strip()
                if _OBJ_ID_RE.match(cand):
                    return cand.lower()
    return None


def _folder_scope(value: str) -> str:
    """A Documentum folder PATH (starts with '/') used only to scope name-based
    discovery. Anything else returns '' so we fall back to the default root."""
    v = (value or "").strip()
    return v if v.startswith("/") else ""


def _looks_like_url(value: str) -> bool:
    v = (value or "").strip()
    return "://" in v or "?" in v or "=" in v


class _FolderPinnedClient:
    """Transparent proxy around EridocClient that intercepts the folder-
    discovery DQL and returns a single synthetic folder record pinned to a
    known object id. Every other call passes straight through, so the engine's
    classification/scoring/validation pipeline runs unchanged."""

    _FOLDER_QUERY_MARK = "FROM dm_folder WHERE object_name"

    def __init__(self, inner, folder_id: str, jira_id: str):
        self._inner = inner
        self._folder_id = folder_id
        self._jira_id = jira_id

    def dql(self, query: str):
        if self._FOLDER_QUERY_MARK in query:
            return [{
                "r_object_id": self._folder_id,
                "object_name": self._jira_id,
                "r_creation_date": "",
                "r_modify_date": "",
            }]
        return self._inner.dql(query)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def run(jira_id: str, eridoc_path: str = "", required: bool = False) -> ScanResult:
    """Entry point. `required` comes from the tool's eridoc_path_mode == REQUIRED.

    Resolution / validation:
      - path blank + required        -> EridocPathError (must provide a path)
      - path blank + not required    -> JIRA-name fallback (allowed)
      - path is folder id / link     -> pin to that folder
      - path starts with "/"         -> scope discovery to that root path
      - path present but unrecognised-> EridocPathError (do NOT silently fall back)
    """
    raw = (eridoc_path or "").strip()

    if not raw:
        if required:
            raise EridocPathError(
                "An ERIDOC Folder Path or link is required for this tool, but "
                "none was provided. Paste the ERIDOC folder link (with locateId) "
                "or a folder path starting with '/'."
            )
        folder_id, scope = None, ""
    else:
        folder_id = _extract_folder_id(raw)
        scope = "" if folder_id else _folder_scope(raw)
        if not folder_id and not scope:
            # A value was given but we can't turn it into a folder id or a
            # "/"-scope. Reject instead of falling back to JIRA-name discovery.
            hint = (
                "It looks like a link but has no folder id (locateId)."
                if _looks_like_url(raw)
                else "Use the full ERIDOC folder link, a 16-character object id, "
                     "or a folder path that starts with '/'."
            )
            raise EridocPathError(
                f"The ERIDOC Folder Path '{raw}' could not be recognised. {hint}"
            )

    if dj.DEMO_MODE:
        return _run_demo(jira_id, folder_id, scope)
    return _run_real(jira_id, folder_id, scope)


def _finding_to_item(f):
    return {
        "code": f.rule_id,
        "title": f.category.replace("_", " ").title(),
        "category": f.category,
        "detail": f.reason,
        "recommendation": f.recommendation,
        "severity": f.severity.value,
        "file": f.file,
        "line": f.line,
        "content": f.matched_text or "",
    }


def _is_accepted_archive(fname: str) -> bool:
    n = (fname or "").lower()
    return n.endswith(_ACCEPTED_ARCHIVE_EXTS)


def _suppress_unsupported_for_archive(f) -> bool:
    """True when this finding is an 'unsupported content' warning for an
    accepted archive (e.g. .zip) — we keep the JIRA-ID naming check but drop
    the 'no content validator' noise."""
    cat = getattr(f, "category", "") or ""
    return cat in _UNSUPPORTED_CATEGORIES and _is_accepted_archive(getattr(f, "file", ""))


def _run_real(jira_id: str, folder_id, scope: str) -> ScanResult:
    from edcs.config import get_settings
    from edcs.document_scanner.scanner import DocumentScanner
    from edcs.eridoc_client.client import EridocClient
    from edcs.models import Severity
    from edcs.exceptions import EridocError

    s = get_settings()
    if scope:
        s = s.model_copy(update={"eridoc_root_path": scope})

    if folder_id:
        client = _FolderPinnedClient(EridocClient(s), folder_id, jira_id)
        scanner = DocumentScanner(s, client=client)
    else:
        scanner = DocumentScanner(s)

    try:
        findings, docs, score, caps = scanner.scan(jira_id)
    except EridocError as e:
        if getattr(e, "retryable", False):
            raise TransientScannerError(str(e)) from e
        raise

    r = ScanResult()
    for f in findings:
        # Accept .zip bundles: drop only the 'unsupported content' warning,
        # keep the naming / integrity checks that fire as other categories.
        if _suppress_unsupported_for_archive(f):
            continue
        item = _finding_to_item(f)
        if f.category in _MISSING_CATEGORIES:
            r.missing_documents.append(item)
        elif f.category in _BLANK_CATEGORIES:
            r.blank_documents.append(item)
        elif f.severity.rank >= Severity.HIGH.rank:
            r.failed_checks.append(item)
        else:
            r.warnings.append(item)

    r.passed_checks.append({
        "code": "ED-SCORE", "title": "Compliance score",
        "detail": f"{score}% (pass threshold {s.compliance_pass_score}%)",
        "recommendation": "", "severity": "INFO", "file": jira_id,
        "category": "SCORE", "line": None, "content": "",
    })

    folder_ok = not any(f.category in _FOLDER_LEVEL for f in findings)
    if folder_ok:
        missing_keys = {it["file"] for it in r.missing_documents}
        for d in scanner.checklist.docs:
            if d.key not in missing_keys:
                r.passed_checks.append({
                    "code": "ED-PRESENT", "title": f"{d.key} present",
                    "detail": "Found in ERIDOC and matched the mandatory checklist.",
                    "recommendation": "", "severity": "INFO", "file": d.key,
                    "category": "DOC_PRESENT", "line": None, "content": "",
                })

    doc_bad = any(f.severity.rank >= Severity.HIGH.rank for f in findings)
    r.status = "FAILED" if (
        score < s.compliance_pass_score or doc_bad
        or r.missing_documents or r.blank_documents
    ) else "PASSED"

    r.stats = {
        "documents_scanned": len(docs),
        "compliance_score": score,
        "compliance_pass_score": s.compliance_pass_score,
        "eridoc_jira_id": jira_id,
        "eridoc_folder_id": folder_id or "",
        "eridoc_root_path": scope or s.eridoc_root_path,
        "eridoc_mode": "folder-link" if folder_id else ("scoped" if scope else "jira-name"),
    }
    return r


def _run_demo(jira_id: str, folder_id=None, scope: str = "") -> ScanResult:
    """Deterministic sample results: JIRA ids ending in an odd digit fail."""
    time.sleep(1.5)
    target = folder_id or jira_id
    r = ScanResult()
    r.passed_checks = [
        {"code": "ED-001", "title": "Test Report present", "detail": "Rev A found",
         "recommendation": "", "severity": "INFO", "file": "TEST_REPORT",
         "category": "DOC_PRESENT", "line": None, "content": ""},
        {"code": "ED-002", "title": "Design Spec present", "detail": "Rev B found",
         "recommendation": "", "severity": "INFO", "file": "DESIGN_SPEC",
         "category": "DOC_PRESENT", "line": None, "content": ""},
    ]
    last = jira_id.strip()[-1] if jira_id.strip() else "1"
    score = 65 if (last.isdigit() and int(last) % 2 == 1) else 96
    if last.isdigit() and int(last) % 2 == 1:
        r.missing_documents = [{
            "code": "EDCS-DOC-004", "title": "Doc Missing", "file": "RELEASE_NOTE",
            "detail": f"Mandatory document 'RELEASE_NOTE' not found in folder {target}",
            "recommendation": f"Upload {jira_id}_RELEASE_NOTE.<ext> to the ERIDOC folder.",
            "severity": "HIGH", "category": "DOC_MISSING", "line": None, "content": "",
        }]
    r.warnings = [{
        "code": "EDCS-DOC-019", "title": "Doc Suspect Small", "file": "TEST_REPORT.pdf",
        "detail": "Document is unusually small for its type - review manually",
        "recommendation": "Verify the document is complete.", "severity": "MEDIUM",
        "category": "DOC_SUSPECT_SMALL", "line": None, "content": "",
    }]
    r.stats = {"documents_scanned": 2 + len(r.missing_documents),
               "compliance_score": score, "compliance_pass_score": 90,
               "eridoc_target": target,
               "eridoc_mode": "folder-link" if folder_id else "jira-name"}
    return r.finalize_status()
