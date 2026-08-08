from django.db import models

WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
            (4, "Friday"), (5, "Saturday"), (6, "Sunday")]


class ToolConfig(models.Model):
    """Step-1 tool catalogue. Decides which scanners run and whether a
    Bitbucket repo URL is required. Data, not code — add tools here."""
    key = models.SlugField(max_length=32, unique=True)          # INHOUSE, RPA, ENABLE, MATE
    display_name = models.CharField(max_length=64)
    requires_repo_url = models.BooleanField(default=False)
    scanners = models.JSONField(default=list,
        help_text='List of scanner keys, e.g. ["ERIDOC", "BITBUCKET"]')
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "key"]

    def __str__(self):
        return self.display_name


class WorkingHours(models.Model):
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS, unique=True)
    is_working = models.BooleanField(default=True)
    start_time = models.TimeField(default="09:00")
    end_time = models.TimeField(default="18:00")

    class Meta:
        ordering = ["weekday"]
        verbose_name_plural = "Working hours"

    def __str__(self):
        return f"{self.get_weekday_display()}: {self.start_time}-{self.end_time}" \
            if self.is_working else f"{self.get_weekday_display()}: off"


class SlotTemplate(models.Model):
    """The fixed catalogue of bookable meeting slots per weekday.
    The scheduler offers ONLY these times (minus blocks/holidays/organizer busy)."""
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["weekday", "sort_order", "start_time"]
        unique_together = [("weekday", "start_time")]

    @property
    def duration_min(self):
        from datetime import date, datetime
        d = date(2000, 1, 3)
        return int((datetime.combine(d, self.end_time) -
                    datetime.combine(d, self.start_time)).total_seconds() // 60)

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} · {self.name}"


class BlockedDate(models.Model):
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["date"]


class BlockedWeekday(models.Model):
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS, unique=True)
    reason = models.CharField(max_length=200, blank=True, default="")


class BlockedTime(models.Model):
    """Blocks a time window. date=NULL means the window is blocked every day."""
    date = models.DateField(null=True, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    reason = models.CharField(max_length=200, blank=True, default="")

    def applies_on(self, d):
        return self.date is None or self.date == d


class EmailTemplate(models.Model):
    KEYS = [("REMINDER", "Meeting reminder"), ("VALIDATION_FAIL", "Validation failed")]
    key = models.CharField(max_length=32, choices=KEYS, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField(help_text="Placeholders: {jira_id} {subject} {start} {join_url} {organizer}")

    def render(self, **ctx):
        return self.subject.format(**ctx), self.body.format(**ctx)


class MeetingTemplate(models.Model):
    key = models.SlugField(max_length=32)
    # NULL = the global fallback template, used when no tool-specific
    # template exists for the booked tool. Set this to scope a template
    # (and its default_attendees) to one tool only.
    tool = models.ForeignKey(ToolConfig, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="meeting_templates",
                             help_text="Leave blank for the global fallback template.")
    subject_pattern = models.CharField(max_length=200, default="Release Review – {jira_id}")
    body_html = models.TextField(default="<p>Release readiness review for <b>{jira_id}</b>.</p>")
    default_attendees = models.JSONField(default=list, help_text='["email1", "email2"]')

    class Meta:
        unique_together = [("key", "tool")]

    def __str__(self):
        return f"{self.key} ({self.tool.display_name})" if self.tool_id else f"{self.key} (global)"


class AppSetting(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict)
    description = models.CharField(max_length=200, blank=True, default="")

    @classmethod
    def get(cls, key, default=None):
        try:
            return cls.objects.get(pk=key).value
        except cls.DoesNotExist:
            return default
