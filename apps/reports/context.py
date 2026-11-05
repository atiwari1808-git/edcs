"""Builds the summary + unified findings list shown in the report and PDF.
Single source of truth so the report, PDF and email never drift apart.
Also normalises the human-readable "Suggested fix" wording.
"""
from __future__ import annotations
_PASSWORD_CATEGORIES = {"SECRET", "CONFIG_CRED"}
_IP_CATEGORIES = {"IPV4", "IPV6"}

# --------------------------------------------------------------------------
# Human-readable "Suggested fix" wording.
# Keyed by finding category; falls back to the finding's own recommendation,
# then to a generic message. This is the SINGLE source of truth used by the
# report, the PDF and the email so the wording never drifts.
# --------------------------------------------------------------------------
_FIX_BY_CATEGORY = {
    # ---- ERIDOC documents ----
    "DOC_FOLDER_MISSING": "Create the project folder in ERIDOC and upload all mandatory documents.",
    "DOC_FOLDER_EMPTY":   "Upload all mandatory documents to the ERIDOC project folder.",
    "DOC_MISSING":        "Upload the missing mandatory document to the ERIDOC folder.",
    "DOC_BLANK":          "Replace the blank document with the complete, reviewed version.",
    "DOC_TITLE_PAGE_ONLY":"Document has only a title page — upload the full content.",
    "DOC_IMAGE_ONLY":     "Document has no readable text — upload a text-based version.",
    "DOC_SUSPECT_SMALL":  "Verify the document is complete; it looks unusually small for its type.",
    # ---- Bitbucket code ----
    "SECRET":       "Move to Database/.env injected at runtime; rotate the exposed value.",
    "CONFIG_CRED":  "Move to Database/.env injected at runtime; rotate the exposed value.",
    "IPV4":         "Move IPs to configuration/database or static sheet; never hardcode.",
    "IPV6":         "Move IPs to configuration/database or static sheet; never hardcode.",
    "HARDCODED_PATH":"Move the path to configuration; do not hardcode environment-specific paths.",
}


def humanize_fix(finding: dict) -> str:
    """Return a clean, user-facing 'Suggested fix' for a finding dict."""
    cat = (finding.get("category") or "").upper()
    if cat in _FIX_BY_CATEGORY:
        return _FIX_BY_CATEGORY[cat]
    rec = (finding.get("recommendation") or "").strip()
    if rec:
        return rec
    return "Review the flagged item and correct it before re-running verification."


def build_report_context(run):
    results = list(run.results.all())
    findings = []
    password_issues = ip_issues = 0
    files_scanned = documents_scanned = 0
    compliance_score = None
    scanner_states = []          # per-scanner status pill on the report
    scan_errors = []             # scanners that could not complete

    for res in results:
        files_scanned += res.stats.get("files_scanned", 0)
        if "documents_scanned" in res.stats:
            documents_scanned += res.stats["documents_scanned"]
        if "compliance_score" in res.stats:
            compliance_score = res.stats["compliance_score"]

        label = "ERIDOC Documents" if res.scanner == "ERIDOC" else "Bitbucket Code"
        scanner_states.append({
            "scanner": res.scanner, "label": label,
            "status": res.status, "error_message": res.error_message,
        })
        if res.status == "ERROR" and res.error_message:
            scan_errors.append({"label": label, "message": res.error_message})

        for bucket in (res.missing_documents, res.blank_documents,
                       res.failed_checks, res.warnings):
            for it in bucket:
                cat = it.get("category", "")
                if cat in _PASSWORD_CATEGORIES:
                    password_issues += 1
                elif cat in _IP_CATEGORIES:
                    ip_issues += 1
                # Normalise the suggested-fix wording; drop internal rule code
                # from user-facing output.
                clean = {**it, "scanner": res.scanner}
                clean["recommendation"] = humanize_fix(it)
                findings.append(clean)

    return {
        "run": run, "findings": findings,
        "password_issues": password_issues, "ip_issues": ip_issues,
        "files_scanned": files_scanned, "documents_scanned": documents_scanned,
        "compliance_score": compliance_score,
        "scanner_states": scanner_states,
        "scan_errors": scan_errors,
    }
