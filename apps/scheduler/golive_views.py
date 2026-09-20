"""
'Mark GO-live done' action (additive, self-contained).

Wired via one path in apps/scheduler/urls.py. Marking a handover GO-live stops
all further GO-live reminders and escalations for that meeting.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.log import log_action
from apps.rbac.decorators import require_permission
from .models import Meeting


@require_permission("schedules.edit")
@require_POST
def mark_go_live(request, meeting_id):
    """Mark a completed handover as moved to GO live — stops follow-ups."""
    m = get_object_or_404(Meeting, pk=meeting_id)
    if m.go_live_done:
        messages.info(request, "This handover is already marked GO-live.")
        return redirect("/")
    m.go_live_done = True
    m.go_live_done_at = timezone.now()
    m.go_live_done_by = request.user
    m.save(update_fields=["go_live_done", "go_live_done_at", "go_live_done_by"])
    jira = m.validation_run.jira_id if m.validation_run else str(m.id)
    log_action(request.user, "meeting.golive", "schedules",
               f"Handover {jira} ({m.tool_key}) marked GO-live.")
    messages.success(request,
                     f"Marked {jira} as GO-live. Follow-up reminders stopped.")
    return redirect("/")
