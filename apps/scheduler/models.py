import uuid
from django.conf import settings
from django.db import models


class DailySlot(models.Model):
    """The fixed daily handover slot(s). Handover model: by default ONE slot
    per day (e.g. 15:00-16:00) shared by every weekday; admins may add more.
    Each (tool, date, slot) combination is exclusive across ALL users."""
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "start_time"]
        unique_together = [("start_time", "end_time")]

    @property
    def label(self):
        return f"{self.start_time:%I:%M %p} - {self.end_time:%I:%M %p}"

    def __str__(self):
        return self.label


class Meeting(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"; CONFIRMED = "CONFIRMED"
        REQUESTED = "REQUESTED"      # PA-email mode: request sent to the Flow
        CANCELLED = "CANCELLED"; FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    validation_run = models.ForeignKey("validation.ValidationRun", null=True,
                                       blank=True, on_delete=models.SET_NULL)
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    # Exclusivity dimensions (Handover model: one booking per tool/date/slot)
    tool_key = models.CharField(max_length=32, blank=True, default="", db_index=True)
    booking_date = models.DateField(null=True, blank=True, db_index=True)
    slot = models.ForeignKey(DailySlot, null=True, blank=True,
                             on_delete=models.PROTECT)
    subject = models.CharField(max_length=200)
    body_html = models.TextField(blank=True, default="")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    graph_event_id = models.CharField(max_length=256, blank=True, default="")
    teams_join_url = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                     blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
        # ── GO-live follow-up tracking (added for post-handover reminders) ──
    go_live_done = models.BooleanField(default=False, db_index=True)
    go_live_done_at = models.DateTimeField(null=True, blank=True)
    go_live_done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    # Stamped once each corresponding email has been sent (idempotency guard)
    golive_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    escalation_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start_at"]
        constraints = [
            # One active booking per tool per date per slot — across ALL users.
            models.UniqueConstraint(
                fields=["tool_key", "booking_date", "slot"],
                condition=models.Q(status__in=["PENDING", "REQUESTED", "CONFIRMED"]),
                name="uniq_tool_date_slot"),
        ]


class MeetingAttendee(models.Model):
    class Kind(models.TextChoices):
        DEVELOPER = "DEVELOPER"; SCRUM_MASTER = "SCRUM_MASTER"
        CC = "CC"; REQUIRED = "REQUIRED"   # REQUIRED = compulsory/backend/organizer

    meeting = models.ForeignKey(Meeting, related_name="attendees",
                                on_delete=models.CASCADE)
    email = models.EmailField()
    type = models.CharField(max_length=16, choices=Kind.choices,
                            default=Kind.REQUIRED)


class Reminder(models.Model):
    meeting = models.ForeignKey(Meeting, related_name="reminders",
                                on_delete=models.CASCADE)
    scheduled_for = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=10, default="SCHEDULED")
