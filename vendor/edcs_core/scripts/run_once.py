"""Manual trigger CLI - the operator's friend and the Phase-1 deliverable.

Usage:
    python scripts/run_once.py --jira ABCD-1234 \
        --repo https://bitbucket.xxx.com/projects/OSS/repos/project [--no-mail]
"""
from __future__ import annotations

import argparse
import sys

from edcs.config import get_settings
from edcs.logger import setup as setup_logging
from edcs.models import ScanJob, Status
from edcs.orchestrator import run_job


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one EDCS scan manually")
    ap.add_argument("--jira", required=True, help="Jira ID, e.g. ABCD-1234")
    ap.add_argument("--repo", required=True, help="Bitbucket repository URL")
    ap.add_argument("--no-mail", action="store_true", help="Skip report email")
    args = ap.parse_args()

    s = get_settings()
    setup_logging(s.log_dir, s.log_level)
    job = ScanJob(jira_id=args.jira.upper(), repo_url=args.repo, requester="cli")
    result = run_job(job, send_mail=not args.no_mail)

    print(f"\nOverall : {result.overall_status.value}")
    print(f"Docs    : {result.doc_status.value}  (compliance {result.compliance_score}%)")
    print(f"Code    : {result.code_status.value}  ({len(result.code_findings)} findings)")
    for cap in result.stats.get("score_caps", []):
        print(f"  - {cap}")
    print(f"Reports : {s.report_dir / job.jira_id}")
    sys.exit(0 if result.overall_status == Status.PASS else 1)


if __name__ == "__main__":
    main()
