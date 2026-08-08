"""Run lifecycle. The scanner set is ALWAYS resolved server-side from
ToolConfig — the client cannot choose which scanners execute."""
from celery import chord
from apps.adminconfig.models import ToolConfig
from apps.scanners.bitbucket_adapter import validate_repo_url
from .models import ValidationRun
from .tasks import run_scanner, finalize_validation


class ValidationError(Exception):
    pass


def start_run(user, tool_key: str, jira_id: str, repo_url: str = "",
              customer_name: str = "", automation_name: str = "") -> ValidationRun:
    try:
        tool = ToolConfig.objects.get(key=tool_key, is_active=True)
    except ToolConfig.DoesNotExist:
        raise ValidationError("Unknown tool.")
    import re
    customer_name = (customer_name or "").strip()
    if not customer_name:
        raise ValidationError("Customer name is required.")
    if len(customer_name) > 200:
        raise ValidationError("Customer name is too long (max 200 characters).")
    if not re.fullmatch(r"[\w .&,\-()/]+", customer_name, flags=re.UNICODE):
        raise ValidationError("Customer name contains invalid characters.")
    automation_name = (automation_name or "").strip()
    if not automation_name:
        raise ValidationError("Automation name is required.")
    if len(automation_name) > 200:
        raise ValidationError("Automation name is too long (max 200 characters).")
    if not re.fullmatch(r"[\w .&,\-()/]+", automation_name, flags=re.UNICODE):
        raise ValidationError("Automation name contains invalid characters.")
    jira_id = jira_id.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", jira_id):
        raise ValidationError("JIRA ID must look like PROJ-1234.")
    if tool.requires_repo_url:
        if not repo_url.strip():
            raise ValidationError("This tool requires a Bitbucket repository URL.")
        if not validate_repo_url(repo_url):
            raise ValidationError("Repository URL host is not on the allow-list.")
    else:
        repo_url = ""                        # silently dropped per design
    if ValidationRun.objects.filter(jira_id=jira_id,
            status__in=["PENDING", "RUNNING"]).exists():
        raise ValidationError(f"A run for {jira_id} is already in progress.")

    run = ValidationRun.objects.create(tool=tool, jira_id=jira_id,
                                       repo_url=repo_url, requested_by=user,
                                       customer_name=customer_name,
                                       automation_name=automation_name,
                                       status=ValidationRun.Status.RUNNING)
    # Pre-create one PENDING row per scanner so the progress UI can render
    # every card immediately (before any task has started).
    from .models import ValidationResult
    for s in tool.scanners:
        ValidationResult.objects.get_or_create(run=run, scanner=s)
    _dispatch(run, tool.scanners)
    return run


def _dispatch(run, scanners):
    """Dispatch scanner tasks.

    Real Celery (ALWAYS_EAGER=False): a chord of per-scanner tasks + finalize,
    exactly as before — task ids land on the result rows for revoke().

    Eager mode (Windows dev, no Redis): chord() would run everything INSIDE
    the web request, blocking the browser until the scan ends — which is why
    RUNNING was never visible and Terminate was impossible. Instead we run
    the same task functions in background daemon threads: the POST returns
    immediately, polling shows live status, and the cooperative cancel flag
    (DB state) works because every checkpoint re-reads the DB."""
    from django.conf import settings as dj
    if not dj.CELERY_TASK_ALWAYS_EAGER:
        header = [run_scanner.s(str(run.id), s) for s in scanners]
        chord(header)(finalize_validation.s(str(run.id)))
        return

    import threading

    def _worker():
        threads = []
        for s in scanners:
            t = threading.Thread(
                target=lambda sc=s: run_scanner.apply(args=(str(run.id), sc)),
                daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        finalize_validation.apply(args=(None, str(run.id)))

    threading.Thread(target=_worker, daemon=True).start()


def cancel_run(user, run) -> tuple[bool, str]:
    """Request cancellation. Cooperative: sets the CANCELLING flag that every
    task checkpoint re-reads; in real-Celery mode additionally revokes any
    known task ids as a hard stop. Idempotent."""
    from django.conf import settings as dj
    from django.utils import timezone
    if run.is_done:
        return False, f"Run is already {run.status} — nothing to cancel."
    if run.status == ValidationRun.Status.CANCELLING:
        return True, "Cancellation already in progress."
    run.status = ValidationRun.Status.CANCELLING
    run.cancelled_by = user
    run.cancelled_at = timezone.now()
    run.save()
    if not dj.CELERY_TASK_ALWAYS_EAGER:
        try:
            from config.celery import app as celery_app
            for r in run.results.exclude(celery_task_id=""):
                celery_app.control.revoke(r.celery_task_id, terminate=True,
                                          signal="SIGTERM")
        except Exception:
            pass  # cooperative flag still applies at the next checkpoint
    return True, "Cancellation requested."
