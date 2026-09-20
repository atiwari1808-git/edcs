"""
Daily GO-live follow-up + escalation runner.

Run once per day via cron (Linux) or Task Scheduler (Windows):

    python manage.py run_handover_followups

This is the reliable path when CELERY_TASK_ALWAYS_EAGER=True (default), where
Celery beat does not run. Idempotent: each reminder/escalation email fires at
most once per meeting, guarded by timestamps on the Meeting row.
"""
from django.core.management.base import BaseCommand
from apps.scheduler.followup_service import run_handover_followups


class Command(BaseCommand):
    help = "Send day-N GO-live reminders and day-M manager escalations for completed handovers."

    def handle(self, *args, **opts):
        counters = run_handover_followups()
        self.stdout.write(self.style.SUCCESS(
            "Handover follow-ups complete: "
            f"scanned={counters['scanned']} "
            f"golive_sent={counters['golive_sent']} "
            f"escalation_sent={counters['escalation_sent']} "
            f"skipped={counters['skipped']}"))
