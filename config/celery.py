import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("edcs_gate")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "dispatch-due-reminders": {
        "task": "apps.scheduler.tasks.dispatch_due_reminders",
        "schedule": 60.0,
    },
}
