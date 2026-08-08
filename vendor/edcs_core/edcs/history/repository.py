"""Repository pattern: SQLite today, PostgreSQL later = connection string."""
from __future__ import annotations

import json

from edcs.history.db import FindingRow, ScanJobRow, make_session
from edcs.models import ScanResult


class HistoryRepository:
    def __init__(self, db_url: str):
        self.Session = make_session(db_url)

    def save(self, r: ScanResult) -> None:
        with self.Session.begin() as s:
            s.merge(ScanJobRow(
                job_id=r.job.job_id, jira_id=r.job.jira_id, repo_url=r.job.repo_url,
                message_id=r.job.message_id or r.job.job_id, requester=r.job.requester,
                received_at=r.job.received_at.replace(tzinfo=None),
                started_at=r.started_at.replace(tzinfo=None),
                finished_at=r.finished_at.replace(tzinfo=None) if r.finished_at else None,
                doc_status=r.doc_status.value, code_status=r.code_status.value,
                overall_status=r.overall_status.value,
                compliance_score=r.compliance_score, stats_json=json.dumps(r.stats)))
            for f in r.doc_findings + r.code_findings:
                s.add(FindingRow(job_id=r.job.job_id, severity=f.severity.value,
                                 category=f.category, file=f.file, line=f.line,
                                 rule_id=f.rule_id, masked_text=f.matched_text,
                                 reason=f.reason, recommendation=f.recommendation))
