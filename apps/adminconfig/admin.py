from django.contrib import admin
from . import models

@admin.register(models.AutomationType)
class AutomationTypeAdmin(admin.ModelAdmin):
    list_display  = ("key", "display_name", "requires_scheduling",
                     "notification_emails", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order", "requires_scheduling")
    fieldsets = (
        (None, {
            "fields": ("key", "display_name", "sort_order", "is_active"),
        }),
        ("Post-Scan Behaviour", {
            "description": (
                "Tick 'Requires scheduling' for Execution-style automations "
                "(scan → user books a handover meeting).  Untick for "
                "document-only types like Healthcheck or Backup."
            ),
            "fields": ("requires_scheduling",),
        }),
        ("Notification Recipients", {
            "description": (
                "These addresses receive the scan-completion email IN ADDITION "
                "to the user who triggered the scan.  Comma-separated."
            ),
            "fields": ("notification_emails",),
        }),
    )

@admin.register(models.ToolConfig)
class ToolConfigAdmin(admin.ModelAdmin):
    list_display  = ("key", "display_name", "requires_repo_url",
                     "scanners", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")

@admin.register(models.MeetingTemplate)
class MeetingTemplateAdmin(admin.ModelAdmin):
    list_display  = ("key", "tool", "subject_pattern")
    list_filter   = ("tool",)
    fields        = ("key", "tool", "subject_pattern", "body_html", "default_attendees")

for m in (models.Holiday, models.BlockedDate, models.EmailTemplate, models.AppSetting):
    admin.site.register(m)

