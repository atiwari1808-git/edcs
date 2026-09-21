from django.db import models

WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
            (4, "Friday"), (5, "Saturday"), (6, "Sunday")]


class AutomationType(models.Model):
    key = models.SlugField(max_length=32, unique=True,
                           help_text='Short identifier used in code, e.g. HEALTHCHECK')
    display_name = models.CharField(max_length=64)
    requires_scheduling = models.BooleanField(
        default=True,
        help_text=(
            "Tick = Execution flow (scan -> schedule meeting). "
            "Untick = Document-only flow (scan -> email report, no meeting)."
        ),
    )
    notification_emails = models.TextField(
        blank=True, default="",
        help_text=(
            "Comma-separated list of email addresses to CC on every scan "
            "completion notification for this type. "
            "Example: manager@ericsson.com, team-lead@ericsson.com"
        ),
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "key"]
        verbose_name = "Automation Type"
        verbose_name_plural = "Automation Types"

    def __str__(self):
        tag = "scheduling" if self.requires_scheduling else "doc-only"
        return f"{self.display_name} ({tag})"

    def get_notification_email_list(self):
        """Return a clean, de-duped list of recipient email addresses."""
        return list(dict.fromkeys(
            e.strip() for e in self.notification_emails.split(",") if e.strip()
        ))


class JiraType(models.Model):
    """Configurable JIRA work-item type shown on the Verify page.

    Seed two rows: Story (requires_parent=False) and Enhancement
    (requires_parent=True). When requires_parent is True the Verify form
    relabels the main JIRA field to 'Parent JIRA' and reveals a separate
    'Enhancement JIRA ID' field; each enhancement is verified and scheduled
    independently but stays linked to its parent story.
    """
    key = models.SlugField(max_length=32, unique=True,
                           help_text="Short identifier, e.g. STORY or ENHANCEMENT")
    display_name = models.CharField(max_length=64)
    requires_parent = models.BooleanField(
        default=False,
        help_text=("Tick for Enhancement-style types: the main JIRA field becomes "
                   "the Parent JIRA and a separate Enhancement JIRA ID is required."))
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "key"]
        verbose_name = "JIRA Type"
        verbose_name_plural = "JIRA Types"

    def __str__(self):
        return self.display_name


class ToolConfig(models.Model):
    ERIDOC_PATH_MODES = [
        ("REQUIRED", "Required - user must enter an ERIDOC folder path"),
        ("OPTIONAL", "Optional - blank falls back to the JIRA-based lookup"),
    ]
    key = models.SlugField(max_length=32, unique=True)
    display_name = models.CharField(max_length=64)
    requires_repo_url = models.BooleanField(default=False)
    scanners = models.JSONField(default=list,
                                help_text='List of scanner keys, e.g. ["ERIDOC", "BITBUCKET"]')
    eridoc_path_mode = models.CharField(
        max_length=8, choices=ERIDOC_PATH_MODES, default="OPTIONAL",
        help_text=("Controls the ERIDOC folder-path field on the Verify page. "
                   "Only relevant when this tool's scanners include ERIDOC. "
                   "REQUIRED = the field must be filled; OPTIONAL = blank falls "
                   "back to the original JIRA-based ERIDOC lookup."))
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "key"]

    def __str__(self):
        return self.display_name

    @property
    def uses_eridoc(self):
        try:
            return "ERIDOC" in (self.scanners or [])
        except TypeError:
            return False


class WorkingHours(models.Model):
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS, unique=True)
    is_working = models.BooleanField(default=True)
    start_time = models.TimeField(default="09:00")
    end_time = models.TimeField(default="18:00")

    class Meta:
        ordering = ["weekday"]
        verbose_name_plural = "Working hours"

    def __str__(self):
        return (f"{self.get_weekday_display()}: {self.start_time}-{self.end_time}"
                if self.is_working else f"{self.get_weekday_display()}: off")


class SlotTemplate(models.Model):
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["weekday", "sort_order", "start_time"]
        unique_together = [("weekday", "start_time")]


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["date"]


class BlockedDate(models.Model):
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["date"]


class BlockedWeekday(models.Model):
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS, unique=True)
    reason = models.CharField(max_length=200, blank=True, default="")


class BlockedTime(models.Model):
    date = models.DateField(blank=True, null=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    reason = models.CharField(max_length=200, blank=True, default="")


class AppSetting(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict)
    description = models.CharField(max_length=200, blank=True, default="")

    @classmethod
    def get(cls, key, default=None):
        row = cls.objects.filter(key=key).first()
        return row.value if row else default


class EmailTemplate(models.Model):
    KEYS = [
        ("REMINDER", "Meeting reminder"),
        ("VALIDATION_FAIL", "Validation failed"),
    ]
    key = models.CharField(max_length=32, choices=KEYS, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField(
        help_text="Placeholders: {jira_id} {subject} {start} {join_url} {organizer}")

    def render(self, **ctx):
        return self.subject.format(**ctx), self.body.format(**ctx)


class MeetingTemplate(models.Model):
    key = models.SlugField(max_length=32)
    tool = models.ForeignKey(ToolConfig, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="meeting_templates")
    subject_pattern = models.CharField(max_length=200,
                                       default="Release Review - {jira_id}")
    body_html = models.TextField(
        default="<p>Release readiness review for <b>{jira_id}</b>.</p>")
    default_attendees = models.JSONField(default=list,
                                         help_text='["email1", "email2"]')

    class Meta:
        unique_together = [("tool", "key")]

    def __str__(self):
        return f"{self.key} ({self.tool.key if self.tool else 'any tool'})"
