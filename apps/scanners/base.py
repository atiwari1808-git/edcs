"""Stable adapter interface between EDCS-Gate and the existing scanners.
Your real ERIDOC / Bitbucket scanners plug in behind ScanResult so their
internal changes (e.g. d2rest response-shape updates) never leak upward."""
from dataclasses import dataclass, field


@dataclass
class ScanResult:
    status: str = "PASSED"                # PASSED | FAILED | ERROR
    # Each check item is a dict:
    #   {code, title, category, detail, recommendation, severity, file,
    #    line, content}
    # `category` is the raw EDCS category (SECRET, IPV4, IPV6, DOC_MISSING...)
    # `line`/`content` come straight from Finding.line / Finding.matched_text
    # (matched_text is ALREADY MASKED by EDCS for secrets — safe to render).
    # `recommendation` is EDCS's own suggested fix, shown as "Suggested fix".
    passed_checks: list = field(default_factory=list)
    failed_checks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    missing_documents: list = field(default_factory=list)  # ERIDOC only
    blank_documents: list = field(default_factory=list)    # ERIDOC only
    stats: dict = field(default_factory=dict)   # e.g. {files_scanned, compliance_score}

    def finalize_status(self):
        self.status = "FAILED" if (self.failed_checks or self.missing_documents
                                   or self.blank_documents) else "PASSED"
        return self


class TransientScannerError(Exception):
    """Network/5xx style errors → Celery retries. A FAILED check is a
    business result, never an exception."""
