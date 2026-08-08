from django.contrib import admin
from .models import Meeting, MeetingAttendee, Reminder


class AttendeeInline(admin.TabularInline):
    model = MeetingAttendee
    extra = 0


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("subject", "organizer", "start_at", "status")
    list_filter = ("status",)
    inlines = [AttendeeInline]


admin.site.register(Reminder)

from .models import DailySlot

@admin.register(DailySlot)
class DailySlotAdmin(admin.ModelAdmin):
    list_display = ("label", "start_time", "end_time", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
