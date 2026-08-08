from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from apps.adminconfig.models import AppSetting, EmailTemplate
from apps.notifications.email import send_templated


def schedule_reminders_for(meeting):
    """Create Reminder rows per admin-configured offsets (minutes)."""
    from .models import Reminder
    offsets = AppSetting.get("reminder_offsets_min", [60, 10])
    for m in offsets:
        when = meeting.start_at - timedelta(minutes=int(m))
        if when > timezone.now():
            Reminder.objects.create(meeting=meeting, scheduled_for=when)


@shared_task
def dispatch_due_reminders():
    """Celery-beat: runs every minute, sends due reminders via SMTP relay."""
    from .models import Reminder
    due = Reminder.objects.select_related("meeting", "meeting__organizer") \
        .filter(status="SCHEDULED", scheduled_for__lte=timezone.now(),
                meeting__status="CONFIRMED")
    for r in due:
        m = r.meeting
        try:
            send_templated("REMINDER",
                to=[a.email for a in m.attendees.all()] + [m.organizer.email],
                ctx=dict(subject=m.subject,
                         start=m.start_at.strftime("%d %b %Y %H:%M %Z"),
                         join_url=m.teams_join_url,
                         organizer=m.organizer.get_full_name() or m.organizer.username,
                         jira_id=m.validation_run.jira_id if m.validation_run else ""))
            r.status = "SENT"
        except Exception:
            r.status = "FAILED"
        r.save()
    return due.count()
