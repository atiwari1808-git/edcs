"""Auth + dashboard.

Self-registration creates INACTIVE accounts and grants the configurable
DEFAULT ROLE (Developer out of the box; an admin can change it on the Users
page). An account stays inactive until someone with the `users.create`
permission activates it from the Users page.
"""
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
                is_active=False)
            # Grant the configurable default role (dynamic RBAC). The legacy
            # `role` label is left at its model default; real permissions come
            # from the assigned Role below.
            try:
                from apps.rbac.views import get_default_role
                from apps.rbac.models import UserRole
                default_role = get_default_role()
                if default_role:
                    UserRole.objects.get_or_create(user=u, role=default_role)
            except Exception:
                pass  # never block registration if RBAC seed isn't ready yet
            notify.registration_received(u)
            messages.success(
                request,
                "Account created! An administrator must activate it before you can sign in.")
            return redirect("/login/")
    return render(request, "register.html", {"errors": errors, "form": form})


# Activation is gated by the dedicated `users.activate` permission so a role
# (e.g. Scrum Master) can be granted ONLY the ability to activate pending
# registrations without any other user-management rights. The broader
# user-admin permissions still imply activation for backward compatibility.
_ACTIVATE_PERMS = ("users.activate", "users.create", "users.edit")


@require_POST
def activate_user(request, user_id):
    if not any(request.user.has_perm_code(p) for p in _ACTIVATE_PERMS):
        messages.error(request, "You don't have permission to activate users.")
        return redirect("/manage/users/")
    u = User.objects.filter(pk=user_id, is_active=False).first()
    if u:
        u.is_active = True
        u.save()
        notify.account_activated(u)
        log_action(request.user, "user.activated", "users", f"Activated '{u.username}'")
        messages.success(request, f"Activated account for {u.username}.")
    else:
        messages.error(request, "Could not activate that account.")
    return redirect("/manage/users/")


@require_permission("users.delete")
@require_POST
def deactivate_user(request, user_id):
    u = User.objects.filter(pk=user_id, is_active=True).first()
    if not u:
        messages.error(request, "Could not deactivate that account.")
        return redirect("/manage/users/")
    if u == request.user:
        messages.error(request, "You can't deactivate your own account.")
        return redirect("/manage/users/")
    if u.is_superuser:
        messages.error(request, "Superuser accounts can't be deactivated here.")
        return redirect("/manage/users/")
    u.is_active = False
    u.save()
    log_action(request.user, "user.deactivated", "users", f"Deactivated '{u.username}'")
    messages.success(request, f"Deactivated account for {u.username}.")
    return redirect("/manage/users/")


@require_permission("dashboard.view")
def dashboard(request):
    """Handover dashboard: stats, filters, bookings table.

    User activation now lives entirely on the Users page, so the dashboard no
    longer surfaces a pending-activation panel.
    """
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
        "no_meeting_runs": no_meeting_runs,
        "sm_scoped":      sm_scoped,
        "sm_scope_email": sm_scope_email,
    })


@require_permission("reports.export")
def dashboard_export(request):
    """Download the (filtered) bookings as an Excel workbook."""
    from apps.scheduler.services import filtered_bookings, bookings_workbook
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
