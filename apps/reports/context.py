"""Builds the summary + unified findings list shown in the report and PDF.
Single source of truth so the two never drift apart."""

_PASSWORD_CATEGORIES = {"SECRET", "CONFIG_CRED"}
_IP_CATEGORIES = {"IPV4", "IPV6"}


def build_report_context(run):
    results = list(run.results.all())
    findings = []
    password_issues = ip_issues = 0
    files_scanned = documents_scanned = 0
    compliance_score = None

    for res in results:
        files_scanned += res.stats.get("files_scanned", 0)
        if "documents_scanned" in res.stats:
            documents_scanned += res.stats["documents_scanned"]
        if "compliance_score" in res.stats:
            compliance_score = res.stats["compliance_score"]
        for bucket in (res.missing_documents, res.blank_documents,
                       res.failed_checks, res.warnings):
            for it in bucket:
                cat = it.get("category", "")
                if cat in _PASSWORD_CATEGORIES:
                    password_issues += 1
                elif cat in _IP_CATEGORIES:
                    ip_issues += 1
                findings.append({**it, "scanner": res.scanner})

    return {
        "run": run, "findings": findings,
        "password_issues": password_issues, "ip_issues": ip_issues,
        "files_scanned": files_scanned, "documents_scanned": documents_scanned,
        "compliance_score": compliance_score,
    }
