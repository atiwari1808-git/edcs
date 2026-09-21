"""ERIDOC document scanner adapter — wired to the real EDCS v1.0.1
DocumentScanner (vendor/edcs_core).
See README.md "Integration" section.

Mapping from edcs.models.Finding -> our ScanResult buckets:
  DOC_FOLDER_MISSING / DOC_FOLDER_EMPTY / DOC_MISSING  -> missing_documents
  DOC_BLANK / DOC_TITLE_PAGE_ONLY / DOC_IMAGE_ONLY      -> blank_documents
  severity >= HIGH (anything else)                      -> failed_checks
  severity < HIGH                                        -> warnings

Every item keeps EDCS's own `recommendation` text so the report can show
"what failed" AND "how to fix it" per finding — this is what powers the
"suggest correction" step in the validation flow.

The `eridoc_path` argument (new) lets the caller point the scan at an explicit
ERIDOC folder path/link. When it is blank the adapter falls back to the
JIRA-based lookup (the original behaviour).
"""
import logging
import time
from django.conf import settings as dj
from .base import ScanResult, TransientScannerError

NAME = "ERIDOC"
log = logging.getLogger(__name__)

_MISSING_CATEGORIES = {"DOC_FOLDER_MISSING", "DOC_FOLDER_EMPTY", "DOC_MISSING"}
_BLANK_CATEGORIES = {"DOC_BLANK", "DOC_TITLE_PAGE_ONLY", "DOC_IMAGE_ONLY"}
_FOLDER_LEVEL = {"DOC_FOLDER_MISSING", "DOC_FOLDER_EMPTY"}


def run(jira_id: str, eridoc_path: str = "") -> ScanResult:
    # The scan target is the explicit ERIDOC folder path when supplied,
    # otherwise the JIRA id (original JIRA-based lookup).
    target = (eridoc_path or "").strip() or jira_id
    return _run_demo(jira_id, target) if dj.DEMO_MODE else _run_real(jira_id, target)


def _finding_to_item(f):
    return {
        "code": f.rule_id,
        "title": f.category.replace("_", " ").title(),
        "category": f.category,
        "detail": f.reason,
        "recommendation": f.recommendation,   # <- shown in the report as "Suggested fix"
        "severity": f.severity.value,
        "file": f.file,
        "line": f.line,               # None for doc findings (no line concept)
        "content": f.matched_text or "",
    }


def _run_real(jira_id: str, target: str) -> ScanResult:
    from edcs.config import get_settings
    from edcs.document_scanner.scanner import DocumentScanner
    from edcs.models import Severity
    from edcs.exceptions import EridocError
    s = get_settings()
    scanner = DocumentScanner(s)
    try:
        # `target` is either the ERIDOC folder path/link or the JIRA id.
        findings, docs, score, caps = scanner.scan(target)
    except EridocError as e:
        # tenacity already retried inside the EDCS client itself; if it
        # still says retryable, give Celery one more shot at the whole task
        if getattr(e, "retryable", False):
            raise TransientScannerError(str(e)) from e
        raise   # terminal -> task ends ERROR, never a false PASS
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
        "recommendation": "", "severity": "INFO", "file": target,
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
        "eridoc_target": target,
    }
    return r


def _run_demo(jira_id: str, target: str) -> ScanResult:
    """Deterministic sample results: JIRA ids ending in an even digit pass."""
    time.sleep(1.5)
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
               "eridoc_target": target}
    return r.finalize_status()
