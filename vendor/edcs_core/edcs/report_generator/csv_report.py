from __future__ import annotations

import csv
from pathlib import Path

from edcs.models import ScanResult


def write_csv(r: ScanResult, dest: Path) -> Path:
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["scan", "severity", "category", "file", "line",
                    "rule_id", "matched_masked", "reason", "recommendation"])
        for scan, findings in (("document", r.doc_findings), ("code", r.code_findings)):
            for f in findings:
                w.writerow([scan, f.severity.value, f.category, f.file,
                            f.line or "", f.rule_id, f.matched_text,
                            f.reason, f.recommendation])
    return dest
