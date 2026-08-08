"""Runs one ScanJob end-to-end; also the worker daemon entry point.

An errored scan must never masquerade as PASS: any unhandled exception marks
the job ERROR, the error report is mailed, the traceback goes to the job log.
"""
from __future__ import annotations

import logging
import time
import traceback

from edcs.code_scanner.scanner import CodeScanner
from edcs.config import get_settings
from edcs.document_scanner.scanner import DocumentScanner
from edcs.history.repository import HistoryRepository
from edcs.logger import clear_job_context, job_log_file, set_job_context
from edcs.logger import setup as setup_logging
from edcs.mailer.smtp_mailer import Mailer
from edcs.models import ScanJob, ScanResult, Status
from edcs.queue import JobQueue
from edcs.report_generator.csv_report import write_csv
from edcs.report_generator.html import render_email_body, write_html
from edcs.report_generator.json_report import write_json
from edcs.utils.fs import janitor
from edcs.utils.timing import timed

log = logging.getLogger(__name__)


def run_job(job: ScanJob, send_mail: bool = True) -> ScanResult:
    s = get_settings()
    set_job_context(job.job_id, job.jira_id)
    handler, log_path = job_log_file(s.log_dir, job.jira_id, job.job_id)
    result = ScanResult(job=job)
    try:
        log.info("Job started: %s / %s", job.jira_id, job.repo_url)

        # -- Part 1: documents --------------------------------------------
        try:
            with timed(result.stats, "doc_scan_seconds"):
                doc_scanner = DocumentScanner(s)
                findings, docs, score, caps = doc_scanner.scan(job.jira_id)
            result.doc_findings, result.documents = findings, docs
            result.compliance_score = score
            result.stats["score_caps"] = caps
        except Exception as e:
            log.exception("Document scan errored")
            result.doc_status = Status.ERROR
            result.stats["doc_scan_error"] = f"{type(e).__name__}: {e}"

        # -- Part 2: code ---------------------------------------------------
        try:
            with timed(result.stats, "code_scan_seconds"):
                result.code_findings = CodeScanner(s).scan(job.repo_url, result.stats)
        except Exception as e:
            log.exception("Code scan errored")
            result.code_status = Status.ERROR
            result.stats["code_scan_error"] = f"{type(e).__name__}: {e}"

        # -- verdict ----------------------------------------------------------
        result.finalize(s.compliance_pass_score, s.fail_threshold)
        if "doc_scan_error" in result.stats:
            result.doc_status = result.overall_status = Status.ERROR
        if "code_scan_error" in result.stats:
            result.code_status = result.overall_status = Status.ERROR

        # -- Part 3: report + mail + history ---------------------------------
        out_dir = s.report_dir / job.jira_id
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{job.jira_id}_{job.job_id}"
        html = write_html(result, s.mandatory_docs_file.parent / "report_templates",
                          out_dir / f"{prefix}_report.html")
        csvf = write_csv(result, out_dir / f"{prefix}_findings.csv")
        jsonf = write_json(result, out_dir / f"{prefix}_report.json")

        try:
            HistoryRepository(s.history_db_url).save(result)
        except Exception:
            log.exception("History persistence failed (job continues)")

        if send_mail:
            body = render_email_body(result,
                                     s.mandatory_docs_file.parent / "report_templates")
            try:
                Mailer(s).send_report(result, body, [html, csvf, jsonf, log_path])
            except Exception:
                log.exception("Report mail failed; reports remain in %s", out_dir)
                result.stats["mail_failed"] = True

        log.info("Job finished: %s -> %s (compliance %d%%)",
                 job.jira_id, result.overall_status.value, result.compliance_score)
        return result
    except Exception:
        log.error("Unhandled job failure:\n%s", traceback.format_exc())
        result.overall_status = Status.ERROR
        return result
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
        clear_job_context()


def worker_loop() -> None:
    s = get_settings()
    setup_logging(s.log_dir, s.log_level)
    removed = janitor(s.clone_dir)
    if removed:
        log.info("Janitor removed %d orphaned clone dirs", removed)
    queue = JobQueue(s.tmp_dir / "queue.db")
    log.info("Worker started; polling queue")
    while True:
        job = queue.lease()
        if job is None:
            time.sleep(5)
            continue
        result = run_job(job)
        queue.complete(job.job_id, result.overall_status != Status.ERROR)


if __name__ == "__main__":
    worker_loop()
