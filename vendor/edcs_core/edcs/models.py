"""Core immutable data models shared across all EDCS modules."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        return {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}[self.value]


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"  # scan itself failed - never silently PASS


@dataclass(frozen=True, slots=True)
class ScanJob:
    jira_id: str
    repo_url: str
    requester: str = ""
    message_id: str = ""
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    doc_id: str
    name: str
    version: str = ""
    owner: str = ""
    created: str = ""
    modified: str = ""
    file_type: str = ""
    size_bytes: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    category: str          # SECRET | IPV4 | IPV6 | CONFIG_CRED | DOC_* | ...
    file: str
    reason: str
    recommendation: str
    rule_id: str = ""
    line: int | None = None
    matched_text: str = ""  # ALWAYS masked before construction (utils.masking)


@dataclass(slots=True)
class ScanResult:
    job: ScanJob
    doc_findings: list[Finding] = field(default_factory=list)
    code_findings: list[Finding] = field(default_factory=list)
    documents: list[DocumentRecord] = field(default_factory=list)
    compliance_score: int = 0
    doc_status: Status = Status.ERROR
    code_status: Status = Status.ERROR
    overall_status: Status = Status.ERROR
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    stats: dict = field(default_factory=dict)

    def finalize(self, pass_score: int, fail_threshold: Severity) -> None:
        self.finished_at = datetime.now(timezone.utc)
        doc_bad = any(f.severity.rank >= Severity.HIGH.rank for f in self.doc_findings)
        self.doc_status = (
            Status.PASS if self.compliance_score >= pass_score and not doc_bad else Status.FAIL
        )
        code_bad = any(f.severity.rank >= fail_threshold.rank for f in self.code_findings)
        self.code_status = Status.FAIL if code_bad else Status.PASS
        self.overall_status = (
            Status.PASS if self.doc_status == Status.PASS and self.code_status == Status.PASS
            else Status.FAIL
        )
