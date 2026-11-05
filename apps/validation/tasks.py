from __future__ import annotations
import time
from celery import shared_task
from django.utils import timezone
from apps.scanners import eridoc_adapter, bitbucket_adapter
from apps.scanners.base import TransientScannerError
from .models import ValidationRun, ValidationResult, ScannerLog

ADAPTERS = {"ERIDOC": eridoc_adapter, "BITBUCKET": bitbucket_adapter}


def _is_cancelling(run_id) -> bool:
    """Cooperative cancellation flag — re-read from DB every checkpoint."""
    return ValidationRun.objects.filter(
        pk=run_id, status=ValidationRun.Status.CANCELLING).exists()


def _humanize_scanner_error(scanner: str, exc: Exception) -> str:
    """Turn a raw scanner exception into a plain-English, actionable message.

    The technical detail is kept (trimmed) at the end so support can still
    diagnose, but the leading sentence is understandable to any user.
    """
    raw = str(exc or "").strip()
    low = raw.lower()
    is_eridoc = (scanner == "ERIDOC")
    src = "ERIDOC" if is_eridoc else "Bitbucket"
    tech = f" (Technical detail: {raw[:220]})" if raw else ""

    # A rejected/blank ERIDOC path already carries a clear, user-facing
    # message — surface it verbatim instead of the generic wording.
    if type(exc).__name__ == "EridocPathError":
        return raw

    # Service down / 5xx / timeout / unreachable (this is the 503 case)
    if any(k in low for k in ("503", "502", "500", "504", "temporarily unavailable",
                              "timed out", "timeout", "connection", "unreachable",
                              "max retries", "gateway", "read timed", "refused")):
        if is_eridoc:
            return ("The ERIDOC service did not respond after several attempts. "
                    "It is either temporarily unavailable, or the ERIDOC folder "
                    "link/path could not be reached. Check that the ERIDOC Folder "
                    "Path is correct and that ERIDOC is online, then re-run the "
                    "verification." + tech)
        return ("The Bitbucket server did not respond after several attempts. "
                "It is either temporarily unavailable or the repository URL could "
                "not be reached. Check that the Bitbucket link is correct and "
                "reachable, then re-run the verification." + tech)

    # Not found / no docs / no repo / empty
    if any(k in low for k in ("404", "not found", "notfound", "no such",
                              "does not exist", "no folder", "no document",
                              "no documents", "no repository", "empty")):
        if is_eridoc:
            return ("No ERIDOC folder or documents could be found for this JIRA ID "
                    "or folder link. Check the ERIDOC Folder Path / link is correct "
                    "and that the required documents have actually been uploaded, "
                    "then re-run the verification." + tech)
        return ("The Bitbucket repository could not be found, or it is empty. "
                "Check the repository URL is correct, that the repo exists, and "
                "that it contains code, then re-run the verification." + tech)

    # Auth / permission
    if any(k in low for k in ("401", "403", "forbidden", "unauthor", "permission",
                              "access denied", "credential", "token")):
        return (f"Access to {src} was denied — this is an authentication or "
                f"permission problem, not a problem with your documents/code. "
                f"Check the {src} link and that EDCS-Gate is allowed to read it, "
                f"then re-run the verification." + tech)

    # Bad / malformed URL
    if any(k in low for k in ("invalid url", "malformed", "could not parse",
                              "bad url", "invalid scheme", "hostname", "no host")):
        return (f"The {src} link appears to be invalid or malformed. Double-check "
                f"the URL / path you entered and re-run the verification." + tech)

    # Generic fallback — still readable
    return (f"The {src} scan could not be completed because of an unexpected error. "
            f"Please verify the {src} link / path is correct and re-run the "
            f"verification. If it keeps failing, share the technical detail below "
            f"with support." + tech)


@shared_task(bind=True, max_retries=3, default_retry_delay=15)
def run_scanner(self, run_id: str, scanner: str):
    run = ValidationRun.objects.get(pk=run_id)
    result, _ = ValidationResult.objects.get_or_create(run=run, scanner=scanner)

    # Checkpoint 1: cancelled before this scanner even started
    if _is_cancelling(run_id):
        result.status = "CANCELLED"
        result.save()
        ScannerLog.objects.create(result=result,
                                  message=f"{scanner} cancelled before start")
        return "CANCELLED"

    result.status = "RUNNING"
    if getattr(self, "request", None) and self.request.id:
        result.celery_task_id = self.request.id
    result.save()
    ScannerLog.objects.create(result=result, message=f"{scanner} started")

    t0 = time.monotonic()
    try:
        adapter = ADAPTERS[scanner]
        if scanner == "ERIDOC":
            _eridoc_required = bool(
                getattr(run.tool, "uses_eridoc", False)
                and getattr(run.tool, "eridoc_path_mode", "") == "REQUIRED"
            )
            scan = adapter.run(run.jira_id, eridoc_path=run.eridoc_path,
                               required=_eridoc_required)
        else:
            scan = adapter.run(run.repo_url)

        # Checkpoint 2: cancel arrived while the scan ran
        if _is_cancelling(run_id):
            result.status = "CANCELLED"
            ScannerLog.objects.create(
                result=result,
                message=f"{scanner} finished but run was cancelled — result discarded")
        else:
            result.status            = scan.status
            result.passed_checks     = scan.passed_checks
            result.failed_checks     = scan.failed_checks
            result.warnings          = scan.warnings
            result.missing_documents = scan.missing_documents
            result.blank_documents   = scan.blank_documents
            result.stats             = scan.stats
            ScannerLog.objects.create(result=result,
                                      message=f"{scanner} finished: {scan.status}")

    except TransientScannerError as exc:
        # Cancelled mid-flight → record cancellation, do not retry.
        if _is_cancelling(run_id):
            result.status = "CANCELLED"
            result.save()
            return "CANCELLED"

        # Retry while attempts remain. Crucially, on the FINAL attempt we do
        # NOT re-raise (which used to let Celery raise MaxRetriesExceededError
        # OUTSIDE this try/except, leaving the row stuck at RUNNING). Instead we
        # record a terminal ERROR with a human-readable message.
        if self.request.retries < self.max_retries:
            ScannerLog.objects.create(
                result=result, level="WARNING",
                message=(f"{scanner} transient error, retrying "
                         f"(attempt {self.request.retries + 1}"
                         f"/{self.max_retries + 1}): {str(exc)[:500]}"))
            raise self.retry(exc=exc)

        result.status        = "ERROR"
        result.error_message = _humanize_scanner_error(scanner, exc)
        result.duration_ms   = int((time.monotonic() - t0) * 1000)
        ScannerLog.objects.create(
            result=result, level="ERROR",
            message=(f"{scanner} failed after {self.max_retries + 1} attempts: "
                     f"{str(exc)[:1500]}"))
        result.save()
        return "ERROR"

    except Exception as exc:   # terminal error — never a false PASS
        result.status        = "ERROR"
        result.error_message = _humanize_scanner_error(scanner, exc)
        result.duration_ms   = int((time.monotonic() - t0) * 1000)
        ScannerLog.objects.create(result=result, level="ERROR",
                                  message=str(exc)[:2000])
        result.save()
        return "ERROR"

    result.duration_ms = int((time.monotonic() - t0) * 1000)
    result.save()
    return result.status


@shared_task
def finalize_validation(_results, run_id: str):
    """Aggregate scanner results → run verdict → PDF → type-aware email.

    Verdict is FAIL-CLOSED: a run PASSES only when every scanner returned
    PASSED. Any ERROR, or any scanner left RUNNING/PENDING (e.g. the worker
    died, or retries were exhausted), forces the whole run to ERROR — so a
    broken scan can NEVER produce a schedulable PASS.
    """
    run = ValidationRun.objects.select_related(
        "requested_by", "tool", "automation_type").get(pk=run_id)
    results  = list(run.results.all())
    statuses = {r.status for r in results}

    if run.status == ValidationRun.Status.CANCELLING or "CANCELLED" in statuses:
        run.status = ValidationRun.Status.CANCELLED
        if not run.cancelled_at:
            run.cancelled_at = timezone.now()
        run.results.filter(status__in=["PENDING", "RUNNING"]).update(
            status="CANCELLED")

    elif not results:
        # Nothing ran at all — cannot be a pass.
        run.status = ValidationRun.Status.ERROR

    elif "ERROR" in statuses or "RUNNING" in statuses or "PENDING" in statuses:
        # A scanner errored, or never finished → fail closed.
        run.status = ValidationRun.Status.ERROR
        # Surface any stuck rows so the UI / report / email tell the truth.
        run.results.filter(status__in=["PENDING", "RUNNING"]).update(
            status="ERROR",
            error_message=("The scan did not complete — the worker stopped "
                           "before finishing. Please re-run the verification."))

    elif "FAILED" in statuses:
        run.status = ValidationRun.Status.FAILED

    elif statuses <= {"PASSED"}:
        run.status = ValidationRun.Status.PASSED

    else:
        # Any unknown status → fail closed rather than risk a false PASS.
        run.status = ValidationRun.Status.ERROR

    run.summary = {
        "passed":   sum(len(r.passed_checks) for r in results),
        "failed":   sum(len(r.failed_checks) + len(r.missing_documents)
                        + len(r.blank_documents) for r in results),
        "warnings": sum(len(r.warnings) for r in results),
    }
    run.finished_at = timezone.now()
    run.save()

    if run.status == ValidationRun.Status.CANCELLED:
        return run.status

    # ── PDF report FIRST, so the notification email can attach it ─────────
    try:
        from apps.reports.pdf import render_run_pdf
        render_run_pdf(run)
        run.refresh_from_db(fields=["pdf_file"])
    except Exception:
        pass  # PDF failure must never flip the verdict or block the email

    # ── Type-aware email notification (with the PDF attached) ─────────────
    try:
        from apps.notifications.email import (
            send_doconly_complete_email,
            send_execution_passed_email,
            send_scan_failed_email,
        )
        at = run.automation_type
        if run.status == ValidationRun.Status.PASSED:
            if at and not at.requires_scheduling:
                send_doconly_complete_email(run)
            else:
                send_execution_passed_email(run)
        else:
            # FAILED or ERROR — send failure notification regardless of type
            send_scan_failed_email(run)
    except Exception:
        pass  # email failure must never flip the verdict

    return run.status
