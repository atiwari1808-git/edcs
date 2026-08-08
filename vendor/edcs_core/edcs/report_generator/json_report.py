from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from edcs.models import ScanResult

SCHEMA_VERSION = "1.0"


def write_json(r: ScanResult, dest: Path) -> Path:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "job": {**asdict(r.job), "received_at": r.job.received_at.isoformat()},
        "overall_status": r.overall_status.value,
        "doc_status": r.doc_status.value,
        "code_status": r.code_status.value,
        "compliance_score": r.compliance_score,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "stats": r.stats,
        "documents": [asdict(d) for d in r.documents],
        "doc_findings": [{**asdict(f), "severity": f.severity.value} for f in r.doc_findings],
        "code_findings": [{**asdict(f), "severity": f.severity.value} for f in r.code_findings],
    }
    dest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return dest
