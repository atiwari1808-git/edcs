"""Seed tools, the daily handover slot, holidays and templates.
Idempotent — safe to re-run. Ongoing changes: use /admin/ instead."""
from datetime import time, date
from django.core.management.base import BaseCommand
from apps.adminconfig.models import (ToolConfig, WorkingHours, Holiday,
                                     EmailTemplate, MeetingTemplate)
from apps.scheduler.models import DailySlot

TOOLS = [
    ("INHOUSE", "In-House", True,  ["ERIDOC", "BITBUCKET"], 1),
    ("ENABLE",  "Enable",   True,  ["ERIDOC", "BITBUCKET"], 2),
    ("MATE",    "MATE",     False, ["ERIDOC"], 3),
    ("RPA",     "RPA",      True,  ["ERIDOC", "BITBUCKET"], 4),
]

# Noida office public holidays (from Handover-Scheduler)
PUBLIC_HOLIDAYS = [
    ("2026-01-01", "New Year"), ("2026-01-26", "Republic Day"),
    ("2026-03-03", "Holi"), ("2026-04-03", "Good Friday"),
    ("2026-05-27", "Bakrid"), ("2026-08-28", "Raksha Bandhan"),
    ("2026-09-04", "Janmashtami"), ("2026-10-02", "Gandhi Jayanti"),
    ("2026-11-09", "Next day of Diwali"), ("2026-11-24", "Guru Nanak Jayanti"),
    ("2026-12-25", "Christmas"),
]


class Command(BaseCommand):
    def handle(self, *args, **opts):
        for key, name, repo, scanners, order in TOOLS:
            ToolConfig.objects.update_or_create(key=key, defaults=dict(
                display_name=name, requires_repo_url=repo, scanners=scanners,
                sort_order=order, is_active=True))
        # One fixed daily handover slot (admins can add more in /admin/)
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
        EmailTemplate.objects.get_or_create(key="VALIDATION_FAIL", defaults=dict(
            subject="Validation FAILED for {jira_id}",
            body="The verification for {jira_id} has failed. Please review the report in Handover Scheduler."))
        MeetingTemplate.objects.get_or_create(key="handover-call", tool=None, defaults=dict(
            subject_pattern="Handover Call – {tool_name} | {jira_id} – {automation_name} [{ref}]",
            body_html="<p>Handover call for <b>{jira_id}</b> "
                      "(Tool: <b>{tool_name}</b>, Automation: <b>{automation_name}</b>). "
                      "Ref: {ref}</p>"))
        self.stdout.write(self.style.SUCCESS("Defaults seeded."))
