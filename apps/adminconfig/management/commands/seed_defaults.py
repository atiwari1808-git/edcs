from datetime import time, date
from django.core.management.base import BaseCommand
from apps.adminconfig.models import (ToolConfig, WorkingHours, Holiday,
                                      EmailTemplate, MeetingTemplate, AutomationType)
from apps.scheduler.models import DailySlot

TOOLS = [
    ("INHOUSE", "In-House", True,  ["ERIDOC", "BITBUCKET"], 1),
    ("ENABLE",  "Enable",   True,  ["ERIDOC", "BITBUCKET"], 2),
    ("MATE",    "MATE",     False, ["ERIDOC"], 3),
    ("RPA",     "RPA",      True,  ["ERIDOC", "BITBUCKET"], 4),
]

AUTOMATION_TYPES = [
    ("HEALTHCHECK", "Healthcheck", False, 1),
    ("BACKUP",      "Backup",      False, 2),
    ("EXECUTION",   "Execution",   True,  3),
]

PUBLIC_HOLIDAYS = [
    ("2026-01-01", "New Year"), ("2026-01-26", "Republic Day"),
    ("2026-03-03", "Holi"), ("2026-04-03", "Good Friday"),
    ("2026-08-15", "Independence Day"), ("2026-10-02", "Gandhi Jayanti"),
    ("2026-12-25", "Christmas"),
]

class Command(BaseCommand):
    def handle(self, *args, **opts):
        for key, name, repo, scanners, order in TOOLS:
            ToolConfig.objects.update_or_create(key=key, defaults=dict(
                display_name=name, requires_repo_url=repo, scanners=scanners,
                sort_order=order, is_active=True))

        for key, name, req_sched, order in AUTOMATION_TYPES:
            obj, created = AutomationType.objects.get_or_create(
                key=key,
                defaults=dict(display_name=name, requires_scheduling=req_sched,
                              sort_order=order, is_active=True))
            if not created:
                AutomationType.objects.filter(key=key).update(
                    display_name=name, requires_scheduling=req_sched, sort_order=order)

        DailySlot.objects.get_or_create(
            start_time=time(15, 0), end_time=time(16, 0),
            defaults=dict(sort_order=1, is_active=True))

        for wd in range(7):
            WorkingHours.objects.get_or_create(weekday=wd, defaults=dict(
                is_working=wd < 5, start_time=time(9, 0), end_time=time(18, 0)))

        for iso, name in PUBLIC_HOLIDAYS:
            Holiday.objects.get_or_create(date=date.fromisoformat(iso),
                                          defaults=dict(name=name))

        EmailTemplate.objects.get_or_create(key="REMINDER", defaults=dict(
            subject="Reminder: {subject} at {start}",
            body="Hello,\n\nThis is a reminder for '{subject}' starting at {start}.\nJoin: {join_url}\n\nOrganizer: {organizer}"))

        self.stdout.write(self.style.SUCCESS("Defaults seeded (including Automation Types)."))

