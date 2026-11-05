from __future__ import annotations
# New minimal view for doc-only go-live (example)
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.validation.models import ValidationRun

@login_required
@require_POST
def mark_doc_go_live(request, run_id):
    run = get_object_or_404(ValidationRun, pk=run_id, automation_type__requires_scheduling=False, status="PASSED")
    if run.go_live_done:
        messages.info(request, "Go Live already marked.")
        return redirect("/")
    run.go_live_done = True
    run.go_live_done_at = timezone.now()
    run.go_live_done_by = request.user
    run.save(update_fields=["go_live_done", "go_live_done_at", "go_live_done_by"])
    messages.success(request, f"Marked {run.jira_id} as Go Live Done.")
    return redirect("/")
