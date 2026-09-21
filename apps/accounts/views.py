"""Auth + dashboard.
Self-registration creates INACTIVE accounts; an admin
activates them (Django admin, or the Activate button on the dashboard)."""
import re
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from apps.audit.log import log_action
from apps.notifications import email as notify
from apps.rbac.decorators import require_permission
from apps.scheduler.models import Meeting
from .models import User

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{3,32}$")


class LoginView(auth_views.LoginView):
    template_name = "login.html"


class LogoutView(auth_views.LogoutView):
    next_page = "/login/"


def register(request):
    errors, form = [], {"username": "", "email": "", "full_name": ""}
    if request.method == "POST":
        form = {k: request.POST.get(k, "").strip()
                for k in ("username", "email", "full_name")}
        pw  = request.POST.get("password", "")
        pw2 = request.POST.get("confirm_password", "")
        if not USERNAME_RE.fullmatch(form["username"]):
            errors.append("Username must be 3-32 characters (letters, numbers, . or _).")
        elif User.objects.filter(username__iexact=form["username"]).exists():
            errors.append("That username is already taken.")
        if "@" not in form["email"] or "." not in form["email"].split("@")[-1]:
            errors.append("Please enter a valid email address.")
        elif User.objects.filter(email__iexact=form["email"]).exists():
            errors.append("An account with that email already exists.")
        if (len(pw) < 8 or not re.search(r"[A-Za-z]", pw)
                or not re.search(r"\d", pw)):
            errors.append(
                "Password must be at least 8 characters with a letter and a number.")
        elif pw != pw2:
            errors.append("Passwords do not match.")
        if not errors:
            names = form["full_name"].split(" ", 1)
            u = User.objects.create_user(
                username=form["username"], email=form["email"], password=pw,
                first_name=names[0], last_name=names[1] if len(names) > 1 else "",
                is_active=False, role=User.Role.SCRUM_MASTER)
            notify.registration_received(u)
            messages.success(
                request,
                "Account created! An administrator must activate it before you can sign in.")
            return redirect("/login/")
    return render(request, "register.html", {"errors": errors, "form": form})


@require_permission("users.edit")
@require_POST
def activate_user(request, user_id):
    u = User.objects.filter(pk=user_id, is_active=False).first()
    if u:
        u.is_active = True
        u.save()
        notify.account_activated(u)
        log_action(request.user, "user.activated", "users",
                   f"Activated '{u.username}'")
        messages.success(request, f"Activated account for {u.username}.")
    else:
        messages.error(request, "Could not activate that account.")
    return redirect("/")


@require_permission("dashboard.view")
def dashboard(request):
    """Handover dashboard: stats, filters, bookings table, admin panels."""
    q             = request.GET.get("q", "").strip()
    tool_filter   = request.GET.get("tool", "")
    status_filter = request.GET.get("status", "")
    jira_type_filter = request.GET.get("jira_type", "")
    date_from     = request.GET.get("date_from", "")
    date_to       = request.GET.get("date_to", "")

    from apps.adminconfig.models import ToolConfig, JiraType
    from apps.scheduler.services import (
        filtered_bookings, booking_stats, no_meeting_stats)
    from apps.validation.models import ValidationRun

    # ── Scrum-master auto-scoping (Req 5) ─────────────────────────────────
    # A user who can see everything (reports.view) sees all bookings by
    # default. Everyone else is scoped to handovers where their own email is
    # the Scrum Master, unless they explicitly request the full list (?all=1).
    can_view_all   = request.user.has_perm_code("reports.view")
    show_all       = request.GET.get("all") == "1"
    sm_scope_email = ""
    sm_scoped      = False
    if not can_view_all and not show_all and (request.user.email or "").strip():
        sm_scope_email = request.user.email.strip()
        sm_scoped      = True

    rows  = filtered_bookings(q, tool_filter, status_filter, date_from, date_to,
                              jira_type=jira_type_filter,
                              sm_scope_email=sm_scope_email)
    stats = {
        **booking_stats(),
        "no_meeting": no_meeting_stats(),
    }
    no_meeting_runs = (
        ValidationRun.objects
        .filter(automation_type__requires_scheduling=False)
        .select_related("requested_by", "tool", "automation_type", "jira_type")
        .order_by("-started_at")[:50]
    )
    pending_users = (
        User.objects.filter(is_active=False).order_by("date_joined")
        if request.user.has_perm_code("users.edit") else []
    )
    return render(request, "dashboard.html", {
        "nav":            "dashboard",
        "bookings":       rows,
        "stats":          stats,
        "tools":          ToolConfig.objects.filter(is_active=True),
        "jira_types":     JiraType.objects.filter(is_active=True),
        "query":          q,
        "tool_filter":    tool_filter,
        "status_filter":  status_filter,
        "jira_type_filter": jira_type_filter,
        "date_from":      date_from,
        "date_to":        date_to,
        "pending_users":  pending_users,
        "no_meeting_runs": no_meeting_runs,
        "sm_scoped":      sm_scoped,
        "sm_scope_email": sm_scope_email,
    })


@require_permission("reports.export")
def dashboard_export(request):
    """Download the (filtered) bookings as an Excel workbook."""
    from apps.scheduler.services import filtered_bookings, bookings_workbook
    # Mirror the dashboard's scrum-master scoping in the export.
    can_view_all   = request.user.has_perm_code("reports.view")
    show_all       = request.GET.get("all") == "1"
    sm_scope_email = ""
    if not can_view_all and not show_all and (request.user.email or "").strip():
        sm_scope_email = request.user.email.strip()
    rows = filtered_bookings(
        request.GET.get("q", "").strip(),
        request.GET.get("tool", ""),
        request.GET.get("status", ""),
        request.GET.get("date_from", ""),
        request.GET.get("date_to", ""),
        jira_type=request.GET.get("jira_type", ""),
        sm_scope_email=sm_scope_email,
    )
    buffer = bookings_workbook(rows)
    resp = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="handover_bookings.xlsx"'
    return resp
