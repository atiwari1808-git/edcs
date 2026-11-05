from __future__ import annotations
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
                "(scan -> user books a handover meeting). Untick for "
                "document-only types like Healthcheck or Backup."
            ),
            "fields": ("requires_scheduling",),
        }),
        ("Notification Recipients", {
            "description": (
                "These addresses receive the scan-completion email IN ADDITION "
                "to the user who triggered the scan. Comma-separated."
            ),
            "fields": ("notification_emails",),
        }),
    )


@admin.register(models.JiraType)
class JiraTypeAdmin(admin.ModelAdmin):
    list_display  = ("display_name", "key", "requires_parent",
                     "is_active", "sort_order")
    list_editable = ("requires_parent", "is_active", "sort_order")
    fieldsets = (
        (None, {
            "fields": ("key", "display_name", "sort_order", "is_active"),
        }),
        ("Parent / Enhancement behaviour", {
            "description": (
                "Tick 'Requires parent' for Enhancement-style types. On the "
                "Verify page the main JIRA field is relabelled 'Parent JIRA' "
                "and a separate 'Enhancement JIRA ID' field appears. Each "
                "enhancement is verified and scheduled independently but stays "
                "linked to its parent story."
            ),
            "fields": ("requires_parent",),
        }),
    )


@admin.register(models.ToolConfig)
class ToolConfigAdmin(admin.ModelAdmin):
    list_display  = ("key", "display_name", "requires_repo_url",
                     "scanners", "eridoc_path_mode", "is_active", "sort_order")
    list_editable = ("eridoc_path_mode", "is_active", "sort_order")




@admin.register(models.HandoverFollowupConfig)
class HandoverFollowupConfigAdmin(admin.ModelAdmin):
    list_display = ("tool", "go_live_reminder_day", "team_emails", "is_active")
    list_filter = ("is_active", "tool")
    fields = ("tool", "team_emails", "go_live_reminder_day", "is_active")


@admin.register(models.EscalationPolicy)
class EscalationPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "escalation_day", "manager_emails", "cc_team", "is_active")
    list_editable = ("escalation_day", "cc_team", "is_active")
    fields = ("name", "manager_emails", "escalation_day", "cc_team", "is_active")
@admin.register(models.MeetingTemplate)
class MeetingTemplateAdmin(admin.ModelAdmin):
    list_display  = ("key", "tool", "subject_pattern")
    list_filter   = ("tool",)
    fields        = ("key", "tool", "subject_pattern", "body_html", "default_attendees")


for m in (models.Holiday, models.BlockedDate, models.EmailTemplate, models.AppSetting):
    admin.site.register(m)
