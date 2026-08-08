from django.contrib import admin
from .models import ValidationRun, ValidationResult, ScannerLog


class ResultInline(admin.TabularInline):
    model = ValidationResult
    extra = 0
    readonly_fields = ("scanner", "status", "duration_ms")


@admin.register(ValidationRun)
class RunAdmin(admin.ModelAdmin):
    list_display = ("jira_id", "tool", "status", "requested_by", "started_at", "finished_at")
    list_filter = ("status", "tool")
    search_fields = ("jira_id",)
    inlines = [ResultInline]


admin.site.register(ScannerLog)
