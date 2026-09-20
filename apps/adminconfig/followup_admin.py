"""
Django admin registration for the GO-live follow-up + escalation config.

Additive module — imported from apps/adminconfig/admin.py (one import line,
see APPLY_GUIDE.md). Keeps the existing admin.py untouched otherwise.
"""
from django.contrib import admin
from .followup_models import HandoverFollowupConfig, EscalationPolicy


@admin.register(HandoverFollowupConfig)
class HandoverFollowupConfigAdmin(admin.ModelAdmin):
    list_display = ("tool", "go_live_day", "team_emails", "is_active")
    list_editable = ("go_live_day", "is_active")
    list_filter = ("is_active",)
    fieldsets = (
        (None, {"fields": ("tool", "is_active")}),
        ("GO-live reminder (per tool)", {
            "description": (
                "When a handover date has passed and the JIRA is not yet "
                "marked GO-live, the team below is emailed on 'GO-live day' "
                "asking them to move the JIRA to GO live."),
            "fields": ("team_emails", "go_live_day"),
        }),
    )


@admin.register(EscalationPolicy)
class EscalationPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "escalation_day", "manager_emails", "cc_team", "is_active")
    list_editable = ("escalation_day", "is_active")
    fieldsets = (
        (None, {"fields": ("name", "is_active")}),
        ("Escalation matrix (global — applies to all tools)", {
            "description": (
                "If the JIRA is still not GO-live by 'escalation day' after "
                "the handover date, these managers are emailed. Keep a SINGLE "
                "active policy — it is shared across every tool."),
            "fields": ("manager_emails", "escalation_day", "cc_team"),
        }),
    )

    def has_add_permission(self, request):
        # Enforce a single global policy row.
        if EscalationPolicy.objects.exists():
            return False
        return super().has_add_permission(request)
