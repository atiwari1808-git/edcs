import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from apps.adminconfig.models import ToolConfig, AutomationType, JiraType
from apps.audit.log import log_action
from apps.rbac.decorators import require_permission
from .models import ValidationRun
from .services import start_run, cancel_run, ValidationError


@require_permission("verification.view")
def verify_page(request):
    """Handover-style 'Verify Documents' screen: form + result cards +
    the user's verification history.
    Result shown when ?run=<id>."""
    result_run = None
    if request.GET.get("run"):
        result_run = (
            ValidationRun.objects
            .filter(pk=request.GET["run"])
            .select_related("automation_type", "jira_type")
            .prefetch_related("results")
            .first()
        )
    history = (
        ValidationRun.objects
        .filter(requested_by=request.user)
        .select_related("tool", "automation_type", "jira_type")
        .prefetch_related("results")
        .order_by("-started_at")[:20]
    )
    return render(request, "verify.html", {
        "nav": "verify",
        "tools": ToolConfig.objects.filter(is_active=True),
        "automation_types": AutomationType.objects.filter(is_active=True),
        "jira_types": JiraType.objects.filter(is_active=True),
        "result_run": result_run,
        "history": history,
    })


@require_permission("verification.execute")
@require_POST
def start(request):
    data = json.loads(request.body or "{}")
    try:
        run = start_run(
            request.user,
            data.get("tool_key", ""),
            data.get("jira_id", ""),
            data.get("repo_url", ""),
            data.get("customer_name", ""),
            data.get("automation_name", ""),
            data.get("automation_type_key", ""),
            jira_type_key=data.get("jira_type_key", ""),
            enhancement_jira_id=data.get("enhancement_jira_id", ""),
            eridoc_path=data.get("eridoc_path", ""),
        )
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    log_action(request.user, "validation.started", "verification",
               f"{run.tool.key} / {run.jira_id} "
               f"(customer: {run.customer_name}, "
               f"type: {run.automation_type.key if run.automation_type else 'N/A'})")
    return JsonResponse({"run_id": str(run.id)}, status=202)


@require_permission("verification.execute")
@require_POST
def cancel(request, run_id):
    run = get_object_or_404(ValidationRun, pk=run_id)
    ok, msg = cancel_run(request.user, run)
    if ok:
        log_action(request.user, "validation.terminated", "verification",
                   f"{run.tool.key} / {run.jira_id}: {msg}")
    return JsonResponse({"ok": ok, "message": msg}, status=202 if ok else 409)


@login_required
def status_json(request, run_id):
    run = get_object_or_404(
        ValidationRun.objects
        .select_related("automation_type")
        .prefetch_related("results"),
        pk=run_id,
    )
    at = run.automation_type
    return JsonResponse({
        "status":             run.status,
        "done":               run.is_done,
        "summary":            run.summary,
        "requires_scheduling": at.requires_scheduling if at else True,
        "automation_type":    at.key if at else None,
        "scanners": [
            {"scanner": r.scanner, "status": r.status,
             "duration_ms": r.duration_ms}
            for r in run.results.all()
        ],
        "next": f"/verify/?run={run.id}",
    })


@require_permission("reports.view")
def report_page(request, run_id):
    run = get_object_or_404(
        ValidationRun.objects.prefetch_related("results"), pk=run_id)
    from apps.reports.context import build_report_context
    ctx = build_report_context(run)
    ctx["nav"] = "verify"
    return render(request, "report.html", ctx)


@require_permission("reports.download")
def report_pdf(request, run_id):
    run = get_object_or_404(ValidationRun, pk=run_id)
    if not run.pdf_file:
        from apps.reports.pdf import render_run_pdf
        render_run_pdf(run)
        run.refresh_from_db()
    if not run.pdf_file:
        raise Http404("PDF not available.")
    log_action(request.user, "report.generated", "reports",
               f"PDF for {run.tool.key} / {run.jira_id}")
    return FileResponse(run.pdf_file.open("rb"), as_attachment=True,
                        filename=f"validation-{run.jira_id}.pdf")


@login_required
def legacy_redirects(request):
    return redirect("/verify/")
