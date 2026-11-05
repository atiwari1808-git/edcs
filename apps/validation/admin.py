from __future__ import annotations
from django.contrib import admin
from django.contrib.admin.sites import NotRegistered

from .models import ValidationRun, ValidationResult, ScannerLog

# Remove any old registrations before re-registering cleanly
for model in (ValidationRun, ValidationResult, ScannerLog):
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass

class ValidationResultInline(admin.TabularInline):
    model = ValidationResult
    extra = 0
    can_delete = True
    show_change_link = True

@admin.register(ValidationRun)
class ValidationRunAdmin(admin.ModelAdmin):
    list_display = (
        "jira_id",
        "tool",
        "automation_type",
        "jira_type",
        "customer_name",
        "automation_name",
        "requested_by",
        "status",
        "started_at",
        "finished_at",
        "doc_scrum_master_email",
        "go_live_done",
    )
    list_filter = (
        "status",
        "tool",
        "automation_type",
        "jira_type",
        "go_live_done",
        "started_at",
    )
    search_fields = (
        "jira_id",
        "customer_name",
        "automation_name",
        "repo_url",
        "eridoc_path",
        "doc_scrum_master_email",
        "requested_by__username",
        "requested_by__email",
        "tool__key",
        "tool__display_name",
    )
    readonly_fields = ("started_at", "finished_at", "pdf_file")
    inlines = [ValidationResultInline]

@admin.register(ValidationResult)
class ValidationResultAdmin(admin.ModelAdmin):
    list_display = ("run", "status")
    list_filter = ("status",)
    search_fields = ("run__jira_id",)

@admin.register(ScannerLog)
class ScannerLogAdmin(admin.ModelAdmin):
    list_display = ("id",)

