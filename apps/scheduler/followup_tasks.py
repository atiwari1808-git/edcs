"""
Celery entry point for the daily GO-live follow-up scan (additive).

Wired into config/celery.py beat schedule (once a day). Under the default
CELERY_TASK_ALWAYS_EAGER=True thread mode, Celery beat is NOT running, so the
management command (run via cron / Windows Task Scheduler) is the reliable
path in that configuration. Both call the same idempotent engine.
"""
import logging
from celery import shared_task

log = logging.getLogger(__name__)


@shared_task
def dispatch_handover_followups():
    from apps.scheduler.followup_service import run_handover_followups
    counters = run_handover_followups()
    log.info("handover follow-ups: %s", counters)
    return counters
