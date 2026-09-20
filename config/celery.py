# celery.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("edcs_gate")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "dispatch-due-reminders": {
        "task": "apps.scheduler.tasks.dispatch_due_reminders",
        "schedule": 60.0,
    },
    # Daily GO-live follow-up + escalation scan (03:30 server time).
    # NOTE: only fires when a real Celery beat + worker are running
    # (CELERY_TASK_ALWAYS_EAGER=False). Under the default EAGER thread mode,
    # run `manage.py run_handover_followups` from cron / Task Scheduler instead.
    "handover-golive-followups": {
        "task": "apps.scheduler.followup_tasks.dispatch_handover_followups",
        "schedule": crontab(hour=3, minute=30),
    },
}
