from __future__ import annotations
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


def _meeting_handover_date(meeting):
    if meeting.booking_date:
        return meeting.booking_date
    return timezone.localtime(meeting.start_at).date()


@shared_task
def dispatch_post_handover_followups():
    """Daily GO-live reminder + escalation dispatcher."""
    from apps.adminconfig.models import HandoverFollowupConfig, EscalationPolicy
    from apps.notifications.handover_emails import golive_reminder_notice, escalation_notice
    from .models import Meeting

    now = timezone.now()
    today = timezone.localdate()
    policy = EscalationPolicy.active()
    cfg_by_tool = {
        c.tool.key: c
        for c in HandoverFollowupConfig.objects.select_related("tool").filter(is_active=True)
    }
    sent = {"team": 0, "escalation": 0}

    meetings = (
        Meeting.objects
        .select_related("organizer", "validation_run", "slot")
        .prefetch_related("attendees")
        .filter(status__in=["PENDING", "REQUESTED", "CONFIRMED"], go_live_done=False)
        .order_by("start_at")
    )

    for m in meetings.iterator():
        handover_date = _meeting_handover_date(m)
        if handover_date >= today:
            continue

        days_old = (today - handover_date).days
        cfg = cfg_by_tool.get(m.tool_key)

        if cfg and days_old >= int(cfg.go_live_reminder_day):
            last = timezone.localtime(m.golive_reminder_sent_at).date() if m.golive_reminder_sent_at else None
            if last != today:
                try:
                    golive_reminder_notice(m, cfg)
                    m.golive_reminder_sent_at = now
                    m.save(update_fields=["golive_reminder_sent_at"])
                    sent["team"] += 1
                except Exception:
                    pass

        if policy and days_old >= int(policy.escalation_day):
            last = timezone.localtime(m.escalation_sent_at).date() if m.escalation_sent_at else None
            if last != today:
                try:
                    escalation_notice(m, policy, cfg=cfg)
                    m.escalation_sent_at = now
                    m.save(update_fields=["escalation_sent_at"])
                    sent["escalation"] += 1
                except Exception:
                    pass

    return sent
