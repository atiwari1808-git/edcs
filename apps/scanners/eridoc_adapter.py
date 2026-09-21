"""ERIDOC document scanner adapter — wired to the real EDCS v1.0.1
DocumentScanner (vendor/edcs_core).
See README.md "Integration" section.

Mapping from edcs.models.Finding -> our ScanResult buckets:
  DOC_FOLDER_MISSING / DOC_FOLDER_EMPTY / DOC_MISSING  -> missing_documents
  DOC_BLANK / DOC_TITLE_PAGE_ONLY / DOC_IMAGE_ONLY      -> blank_documents
  severity >= HIGH (anything else)                      -> failed_checks
  severity < HIGH                                        -> warnings

Every item keeps EDCS's own `recommendation` text so the report can show
"what failed" AND "how to fix it" per finding.

ERIDOC Folder Path field (`eridoc_path`) — accepts one of:
  1. A real ERIDOC web link with a folder object id, e.g.
        https://eridoc.internal.ericsson.com/eridoc/?docbase=eridoca&locateId=0b004cffd9ad177d
     -> the scan is pinned to that EXACT folder (object id from `locateId`),
        bypassing JIRA-name-based folder discovery.
  2. A raw 16-char Documentum object id (e.g. 0b004cffd9ad177d) -> same as (1).
  3. A Documentum folder PATH starting with "/" -> used to scope name-based
     discovery (root-path override).
  4. Blank / unrecognised -> falls back to the original JIRA-based lookup.
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

# Documentum r_object_id: 16 hex chars. Folder objects carry the "0b" type tag.
_OBJ_ID_RE = re.compile(r"^[0-9a-fA-F]{16}$")
# Query-string keys that may carry the folder object id, in priority order.
_ID_PARAM_KEYS = ("locateId", "objectId", "id", "r_object_id", "folderId")


def _extract_folder_id(value: str) -> str | None:
    """Pull a 16-char Documentum object id out of an ERIDOC link, or accept a
    bare object id. Returns None when the value isn't an id-bearing link."""
    v = (value or "").strip()
    if not v:
        return None
    # bare object id
    if _OBJ_ID_RE.match(v):
        return v.lower()
    if "://" not in v and "?" not in v and "=" not in v:
        return None  # not a URL and not an id -> treat as path elsewhere
    try:
        qs = parse_qs(urlparse(v).query)
    except Exception:
        return None
    for key in _ID_PARAM_KEYS:
        # case-insensitive key match
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


class _FolderPinnedClient:
    """Transparent proxy around EridocClient that intercepts the folder-
    discovery DQL and returns a single synthetic folder record pinned to a
    known object id. Every other call (documents_query, download, versions...)
    passes straight through, so the engine's classification/scoring/validation
    pipeline runs unchanged against the exact folder from the ERIDOC link."""

    # signature of dql.folder_query(...) output
    _FOLDER_QUERY_MARK = "FROM dm_folder WHERE object_name"

    def __init__(self, inner, folder_id: str, jira_id: str):
        self._inner = inner
        self._folder_id = folder_id
        self._jira_id = jira_id

    def dql(self, query: str):
        if self._FOLDER_QUERY_MARK in query:
            # Pin discovery to the exact folder from the link.
            return [{
                "r_object_id": self._folder_id,
                "object_name": self._jira_id,
                "r_creation_date": "",
                "r_modify_date": "",
            }]
        return self._inner.dql(query)

    def __getattr__(self, name):
        # delegate download(), and anything else, to the real client
        return getattr(self._inner, name)


def run(jira_id: str, eridoc_path: str = "") -> ScanResult:
    folder_id = _extract_folder_id(eridoc_path)
    scope = "" if folder_id else _folder_scope(eridoc_path)
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


def _run_real(jira_id: str, folder_id: str | None, scope: str) -> ScanResult:
    from edcs.config import get_settings
    from edcs.document_scanner.scanner import DocumentScanner
    from edcs.eridoc_client.client import EridocClient
    from edcs.models import Severity
    from edcs.exceptions import EridocError
    s = get_settings()
    # Never mutate the lru_cache'd singleton; make a per-scan copy so an
    # explicit folder path doesn't leak into later runs.
    if scope:
        s = s.model_copy(update={"eridoc_root_path": scope})

    if folder_id:
        # Option B: pin the scan to the EXACT folder from the ERIDOC link.
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


def _run_demo(jira_id: str, folder_id: str | None = None, scope: str = "") -> ScanResult:
    """Deterministic sample results: JIRA ids ending in an even digit pass."""
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
