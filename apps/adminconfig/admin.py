from django.contrib import admin
from . import models

# ── Active models ────────────────────────────────────────────────────
# The scheduler engine (apps.scheduler.DailySlot + Holiday + BlockedDate)
# replaced the older organizer-availability design these once supported.
# SlotTemplate, WorkingHours, BlockedWeekday, and BlockedTime below have
# no remaining references anywhere in the app's views/services/tasks —
# they're unregistered here (not deleted) so the admin sidebar reflects
# what's actually in use. Their tables/data are untouched; re-register
# them below if you ever revive that flow.


@admin.register(models.ToolConfig)
class ToolConfigAdmin(admin.ModelAdmin):
    list_display = ("key", "display_name", "requires_repo_url", "scanners", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")


@admin.register(models.MeetingTemplate)
class MeetingTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "tool", "subject_pattern")
    list_filter = ("tool",)
    fields = ("key", "tool", "subject_pattern", "body_html", "default_attendees")


for m in (models.Holiday, models.BlockedDate, models.EmailTemplate, models.AppSetting):
    admin.site.register(m)

# ── Unused, kept unregistered — see note above ─────────────────────────
# admin.site.register(models.SlotTemplate)
# admin.site.register(models.WorkingHours)
# admin.site.register(models.BlockedWeekday)
# admin.site.register(models.BlockedTime)
