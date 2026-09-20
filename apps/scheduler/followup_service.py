"""
Post-handover GO-live follow-up + escalation engine (additive, self-contained).

`run_handover_followups()` is idempotent and safe to run repeatedly (daily).
It is called from BOTH:
  * the Celery beat task  apps.scheduler.followup_tasks.dispatch_handover_followups
  * the management command  manage.py run_handover_followups

Logic
-----
For every meeting whose handover date has PASSED, that is not cancelled/failed,
and that has NOT been marked GO-live:

  days_since = today - handover_date
  - if days_since >= per-tool go_live_day  and the day-10 team reminder has not
    been sent  -> send GO-live reminder to the tool team, stamp golive_reminder_sent_at
  - if days_since >= global escalation_day and the day-15 escalation has not
    been sent  -> send escalation to global managers, stamp escalation_sent_at

Timestamps on the Meeting row guarantee each email fires exactly once.
"""
from datetime import date

from apps.notifications import handover_emails


# Statuses that represent a handover that actually happened.
_ACTIVE = ["REQUESTED", "CONFIRMED", "PENDING"]


def run_handover_followups(today: date | None = None) -> dict:
    """Scan + dispatch. Returns a small counters dict for logging/CLI output."""
    from apps.scheduler.models import Meeting
    from apps.adminconfig.followup_models import (
        HandoverFollowupConfig, EscalationPolicy)

    today = today or date.today()
    policy = EscalationPolicy.current()

    counters = {"scanned": 0, "golive_sent": 0, "escalation_sent": 0, "skipped": 0}

    qs = (Meeting.objects
          .filter(status__in=_ACTIVE, go_live_done=False)
          .select_related("organizer", "slot", "validation_run"))

    for m in qs:
        handover_date = m.booking_date or (m.start_at.date() if m.start_at else None)
        if not handover_date or handover_date >= today:
            counters["skipped"] += 1
            continue  # handover not completed yet

        counters["scanned"] += 1
        days_since = (today - handover_date).days
        cfg = HandoverFollowupConfig.for_tool_key(m.tool_key)

        # ── day-10 team GO-live reminder ─────────────────────────────────
        if (cfg and cfg.team_email_list()
                and m.golive_reminder_sent_at is None
                and days_since >= cfg.go_live_day):
            try:
                handover_emails.golive_reminder_notice(m, cfg)
                from django.utils import timezone
                m.golive_reminder_sent_at = timezone.now()
                m.save(update_fields=["golive_reminder_sent_at"])
                counters["golive_sent"] += 1
            except Exception:
                pass

        # ── day-15 global manager escalation ─────────────────────────────
        if (policy and policy.manager_email_list()
                and m.escalation_sent_at is None
                and days_since >= policy.escalation_day):
            try:
                handover_emails.escalation_notice(m, policy, cfg)
                from django.utils import timezone
                m.escalation_sent_at = timezone.now()
                m.save(update_fields=["escalation_sent_at"])
                counters["escalation_sent"] += 1
            except Exception:
                pass

    return counters
