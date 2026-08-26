import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class ValidationRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"; RUNNING = "RUNNING"; PASSED = "PASSED"
        FAILED = "FAILED"; ERROR = "ERROR"
        CANCELLING = "CANCELLING"; CANCELLED = "CANCELLED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tool = models.ForeignKey("adminconfig.ToolConfig", on_delete=models.PROTECT)
    customer_name = models.CharField(max_length=200, blank=True, default="")
    automation_name = models.CharField(max_length=200, blank=True, default="")
    automation_type = models.ForeignKey(
        "adminconfig.AutomationType",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="validation_runs",
        help_text="Controls post-scan behaviour and who is notified.",
    )
    jira_id = models.CharField(max_length=32, db_index=True)
    repo_url = models.URLField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict)      # {passed, failed, warnings}
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                     blank=True, on_delete=models.SET_NULL,
                                     related_name="cancelled_runs")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    pdf_file = models.FileField(upload_to="reports/", blank=True, default="")

    @property
    def requires_scheduling(self):
        if self.automation_type is None:
            return True
        return self.automation_type.requires_scheduling

    class Meta:
        ordering = ["-started_at"]

    @property
    def is_done(self):
        return self.status in (self.Status.PASSED, self.Status.FAILED,
                               self.Status.ERROR, self.Status.CANCELLED)

    @classmethod
    def pass_rate_last_30_days(cls):
        qs = cls.objects.filter(started_at__gte=timezone.now() - timezone.timedelta(days=30),
                                status__in=["PASSED", "FAILED"])
        total = qs.count()
        return round(100 * qs.filter(status="PASSED").count() / total) if total else 0


class ValidationResult(models.Model):
    run = models.ForeignKey(ValidationRun, related_name="results", on_delete=models.CASCADE)
    scanner = models.CharField(max_length=16)          # ERIDOC | BITBUCKET
    status = models.CharField(max_length=10, default="PENDING")
    passed_checks = models.JSONField(default=list)
    failed_checks = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    missing_documents = models.JSONField(default=list)
    blank_documents = models.JSONField(default=list)
    stats = models.JSONField(default=dict)   # {files_scanned, compliance_score, ...}
    celery_task_id = models.CharField(max_length=64, blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        unique_together = [("run", "scanner")]


class ScannerLog(models.Model):
    result = models.ForeignKey(ValidationResult, related_name="logs",
                               on_delete=models.CASCADE)
    ts = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=10, default="INFO")
    message = models.TextField()
