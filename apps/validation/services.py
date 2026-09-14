"""Run lifecycle. The scanner set is ALWAYS resolved server-side from
ToolConfig — the client cannot choose which scanners execute."""
import re
from celery import chord
from apps.adminconfig.models import ToolConfig, AutomationType
from apps.scanners.bitbucket_adapter import validate_repo_url
from .models import ValidationRun
from .tasks import run_scanner, finalize_validation


class ValidationError(Exception):
    pass


def start_run(user, tool_key: str, jira_id: str, repo_url: str = "",
              customer_name: str = "", automation_name: str = "",
              automation_type_key: str = "") -> ValidationRun:
    try:
        tool = ToolConfig.objects.get(key=tool_key, is_active=True)
    except ToolConfig.DoesNotExist:
        raise ValidationError("Unknown tool.")

    # ── Validate customer_name ────────────────────────────────────────────
    customer_name = (customer_name or "").strip()
    if not customer_name:
        raise ValidationError("Customer name is required.")
    if len(customer_name) > 200:
        raise ValidationError("Customer name is too long (max 200 characters).")
    if not re.fullmatch(r"[\w .&,\-()/]+", customer_name, flags=re.UNICODE):
        raise ValidationError("Customer name contains invalid characters.")

    # ── Validate automation_name ──────────────────────────────────────────
    automation_name = (automation_name or "").strip()
    if not automation_name:
        raise ValidationError("Automation name is required.")
    if len(automation_name) > 200:
        raise ValidationError("Automation name is too long (max 200 characters).")
    if not re.fullmatch(r"[\w .&,\-()/]+", automation_name, flags=re.UNICODE):
        raise ValidationError("Automation name contains invalid characters.")

    # ── Validate automation_type (optional — falls back gracefully) ───────
    automation_type = None
    if automation_type_key:
        automation_type = AutomationType.objects.filter(
            key=automation_type_key, is_active=True).first()
        if automation_type is None:
            raise ValidationError("Selected automation type is not valid.")

    # ── Per-day quota for "no-meeting-needed" (doc-only) verifications ────
    # Only applies when the chosen automation type does NOT require
    # scheduling (Healthcheck / Backup). Semantics of the role field:
    #   None -> unlimited, 0 -> not allowed at all, N -> at most N per day.
    if automation_type is not None and not automation_type.requires_scheduling:
        from apps.rbac.permissions import user_daily_limit
        from django.utils import timezone as _tz
        cap = user_daily_limit(user, "max_nmn_verifications_per_day")
        if cap is not None:
            if cap == 0:
                raise ValidationError(
                    "Your role does not permit running no-meeting-needed "
                    "(document-only) verifications. Please contact an "
                    "administrator.")
            run_today = ValidationRun.objects.filter(
                requested_by=user,
                automation_type__requires_scheduling=False,
                started_at__date=_tz.localdate()).count()
            if run_today >= cap:
                raise ValidationError(
                    f"Daily limit reached: your role allows {cap} "
                    f"no-meeting-needed verification(s) per day. Please try "
                    f"again tomorrow or ask an administrator.")

    # ── Validate JIRA ID ─────────────────────────────────────────────────
    jira_id = jira_id.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", jira_id):
        raise ValidationError("JIRA ID must look like PROJ-1234.")

    # ── Validate repo URL ─────────────────────────────────────────────────
    if tool.requires_repo_url:
        if not repo_url.strip():
            raise ValidationError("This tool requires a Bitbucket repository URL.")
        if not validate_repo_url(repo_url):
            raise ValidationError("Repository URL host is not on the allow-list.")
    else:
        repo_url = ""   # silently dropped per design

    # ── Prevent duplicate in-progress runs ───────────────────────────────
    if ValidationRun.objects.filter(
            jira_id=jira_id, status__in=["PENDING", "RUNNING"]).exists():
        raise ValidationError(f"A run for {jira_id} is already in progress.")

    # ── Create the run ────────────────────────────────────────────────────
    run = ValidationRun.objects.create(
        tool=tool,
        jira_id=jira_id,
        repo_url=repo_url,
        requested_by=user,
        customer_name=customer_name,
        automation_name=automation_name,
        automation_type=automation_type,      # ← new FK
        status=ValidationRun.Status.RUNNING,
    )
    # Pre-create one PENDING row per scanner so the progress UI can render
    # every card immediately (before any task has started).
    from .models import ValidationResult
    for s in tool.scanners:
        ValidationResult.objects.get_or_create(run=run, scanner=s)
    _dispatch(run, tool.scanners)
    return run


def _dispatch(run, scanners):
    """Dispatch scanner tasks.
    Real Celery (ALWAYS_EAGER=False): a chord of per-scanner tasks + finalize.
    Eager mode (Windows dev, no Redis): runs in background daemon threads so
    the POST returns immediately and polling shows live status.
    """
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
    """Request cancellation (cooperative + Celery revoke)."""
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
