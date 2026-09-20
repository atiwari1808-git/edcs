# ============================================================================
# ADD THESE FIELDS to the Meeting model in apps/scheduler/models.py
# (paste inside class Meeting, e.g. right after `cancellation_reason`)
# ============================================================================

    # ── GO-live follow-up tracking (added for post-handover reminders) ──
    go_live_done = models.BooleanField(default=False, db_index=True)
    go_live_done_at = models.DateTimeField(null=True, blank=True)
    go_live_done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    # Stamped once each corresponding email has been sent (idempotency guard)
    golive_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    escalation_sent_at = models.DateTimeField(null=True, blank=True)
