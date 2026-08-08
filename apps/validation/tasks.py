import time
from celery import shared_task
from django.utils import timezone

from apps.scanners import eridoc_adapter, bitbucket_adapter
from apps.scanners.base import TransientScannerError
from .models import ValidationRun, ValidationResult, ScannerLog

ADAPTERS = {"ERIDOC": eridoc_adapter, "BITBUCKET": bitbucket_adapter}


def _is_cancelling(run_id) -> bool:
    """Cooperative cancellation flag: re-read from DB (works identically for
    Celery workers and the threading fallback)."""
    return ValidationRun.objects.filter(
        pk=run_id, status=ValidationRun.Status.CANCELLING).exists()


@shared_task(bind=True, max_retries=3, default_retry_delay=15,
             autoretry_for=(TransientScannerError,))
def run_scanner(self, run_id: str, scanner: str):
    run = ValidationRun.objects.get(pk=run_id)
    result, _ = ValidationResult.objects.get_or_create(run=run, scanner=scanner)

    # Checkpoint 1: cancelled before this scanner even started
    if _is_cancelling(run_id):
        result.status = "CANCELLED"
        result.save()
        ScannerLog.objects.create(result=result, message=f"{scanner} cancelled before start")
        return "CANCELLED"

    result.status = "RUNNING"
    if getattr(self, "request", None) and self.request.id:
        result.celery_task_id = self.request.id
    result.save()
    ScannerLog.objects.create(result=result, message=f"{scanner} started")
    t0 = time.monotonic()
    try:
        adapter = ADAPTERS[scanner]
        scan = (adapter.run(run.jira_id) if scanner == "ERIDOC"
                else adapter.run(run.repo_url))
        # Checkpoint 2: cancel arrived while the scan ran — honour it over the
        # scan verdict so the run converges to CANCELLED, and don't present a
        # result the user asked to abandon.
        if _is_cancelling(run_id):
            result.status = "CANCELLED"
            ScannerLog.objects.create(result=result,
                message=f"{scanner} finished but run was cancelled — result discarded")
        else:
            result.status = scan.status
            result.passed_checks = scan.passed_checks
            result.failed_checks = scan.failed_checks
            result.warnings = scan.warnings
            result.missing_documents = scan.missing_documents
            result.blank_documents = scan.blank_documents
            result.stats = scan.stats
            ScannerLog.objects.create(result=result, message=f"{scanner} finished: {scan.status}")
    except TransientScannerError:
        if _is_cancelling(run_id):
            result.status = "CANCELLED"
            result.save()
            return "CANCELLED"
        raise                                # retried by Celery
    except Exception as exc:                 # terminal error — never false PASS
        result.status = "ERROR"
        result.error_message = str(exc)[:2000]
        ScannerLog.objects.create(result=result, level="ERROR", message=str(exc)[:2000])
    result.duration_ms = int((time.monotonic() - t0) * 1000)
    result.save()
    return result.status


@shared_task
def finalize_validation(_results, run_id: str):
    """Aggregate scanner results into the run verdict + PDF."""
    run = ValidationRun.objects.get(pk=run_id)
    results = list(run.results.all())
    statuses = {r.status for r in results}
    if run.status == ValidationRun.Status.CANCELLING or "CANCELLED" in statuses:
        run.status = ValidationRun.Status.CANCELLED
        if not run.cancelled_at:
            run.cancelled_at = timezone.now()
        # normalise any leftover PENDING/RUNNING rows
        run.results.filter(status__in=["PENDING", "RUNNING"]).update(status="CANCELLED")
    elif "ERROR" in statuses:
        run.status = ValidationRun.Status.ERROR
    elif "FAILED" in statuses:
        run.status = ValidationRun.Status.FAILED
    else:
        run.status = ValidationRun.Status.PASSED
    run.summary = {
        "passed": sum(len(r.passed_checks) for r in results),
        "failed": sum(len(r.failed_checks) + len(r.missing_documents)
                      + len(r.blank_documents) for r in results),
        "warnings": sum(len(r.warnings) for r in results),
    }
    run.finished_at = timezone.now()
    run.save()
    if run.status != ValidationRun.Status.CANCELLED:
        try:
            from apps.notifications.email import verification_result
            verification_result(run.requested_by, run.tool.display_name,
                                run.jira_id, run.status)
        except Exception:
            pass
        try:
            from apps.reports.pdf import render_run_pdf
            render_run_pdf(run)
        except Exception:
            pass  # PDF failure must not flip the verdict
    return run.status
