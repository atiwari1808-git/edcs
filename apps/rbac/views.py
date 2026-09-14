from itertools import groupby

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.audit.log import log_action
from .decorators import require_permission
from .models import Permission, Role, RolePermission, UserRole


def _grouped_permissions():
    """Permissions grouped by module, in catalogue order, for the checkbox UI."""
    perms = list(Permission.objects.order_by("module", "action"))
    return [(module, list(group)) for module, group in groupby(perms, key=lambda p: p.module)]


@require_permission("roles.view")
def role_list(request):
    roles = Role.objects.prefetch_related("permissions").all()
    return render(request, "rbac/role_list.html", {
        "nav": "roles", "roles": roles,
    })


@require_permission("roles.create")
def role_create(request):
    if request.method == "POST":
        return _save_role(request, role=None)
    return render(request, "rbac/role_form.html", {
        "nav": "roles", "role": None, "grouped_permissions": _grouped_permissions(),
        "checked": set(),
    })


@require_permission("roles.edit")
def role_edit(request, role_id):
    role = get_object_or_404(Role, pk=role_id)
    if request.method == "POST":
        return _save_role(request, role=role)
    checked = set(role.permissions.values_list("codename", flat=True))
    return render(request, "rbac/role_form.html", {
        "nav": "roles", "role": role, "grouped_permissions": _grouped_permissions(),
        "checked": checked,
    })


def _parse_limit(raw):
    """Parse a per-day quota field from the form.
    Returns (value, error). value is None for blank (unlimited) or an int >= 0."""
    raw = (raw or "").strip()
    if raw == "":
        return None, None
    if not raw.isdigit():
        return None, "must be a whole number (or left blank for unlimited)."
    return int(raw), None


def _save_role(request, role):
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    codenames = set(request.POST.getlist("permissions"))
    if not name:
        messages.error(request, "Role name is required.")
        return redirect(request.path)

    max_meetings, err = _parse_limit(request.POST.get("max_meetings_per_day"))
    if err:
        messages.error(request, f"Max handover meetings per day {err}")
        return redirect(request.path)
    max_nmn, err = _parse_limit(request.POST.get("max_nmn_verifications_per_day"))
    if err:
        messages.error(request, f"Max no-meeting-needed verifications per day {err}")
        return redirect(request.path)

    is_new = role is None
    if is_new:
        if Role.objects.filter(name__iexact=name).exists():
            messages.error(request, f"A role named '{name}' already exists.")
            return redirect("role-create")
        role = Role.objects.create(
            name=name, description=description,
            max_meetings_per_day=max_meetings,
            max_nmn_verifications_per_day=max_nmn)
    else:
        role.name = name
        role.description = description
        role.max_meetings_per_day = max_meetings
        role.max_nmn_verifications_per_day = max_nmn
        role.save()

    valid_perms = list(Permission.objects.filter(codename__in=codenames))
    RolePermission.objects.filter(role=role).delete()
    RolePermission.objects.bulk_create(
        [RolePermission(role=role, permission=p) for p in valid_perms])

    log_action(request.user, "role.created" if is_new else "role.updated", "roles",
              f"Role '{role.name}' ({len(valid_perms)} permissions)")
    if not is_new:
        log_action(request.user, "permission.updated", "roles",
                  f"Permissions for role '{role.name}' set to: "
                  f"{', '.join(sorted(codenames)) or '(none)'}")
    messages.success(request, f"Role '{role.name}' saved with {len(valid_perms)} permission(s).")
    return redirect("role-list")


@require_permission("roles.delete")
@require_POST
def role_delete(request, role_id):
    role = get_object_or_404(Role, pk=role_id)
    if role.is_system:
        messages.error(request, f"'{role.name}' is a starter role and can't be deleted "
                                "(you can still edit its permissions freely).")
        return redirect("role-list")
    assigned = UserRole.objects.filter(role=role).count()
    if assigned:
        messages.error(request, f"Can't delete '{role.name}': {assigned} user(s) still "
                                "hold it. Reassign them first.")
        return redirect("role-list")
    name = role.name
    role.delete()
    log_action(request.user, "role.deleted", "roles", f"Role '{name}' deleted")
    messages.success(request, f"Role '{name}' deleted.")
    return redirect("role-list")


@require_permission("roles.create")
@require_POST
def role_clone(request, role_id):
    src = get_object_or_404(Role, pk=role_id)
    base_name = f"{src.name} (copy)"
    name, n = base_name, 2
    while Role.objects.filter(name=name).exists():
        name = f"{base_name} {n}"; n += 1
    clone = Role.objects.create(
        name=name, description=src.description,
        max_meetings_per_day=src.max_meetings_per_day,
        max_nmn_verifications_per_day=src.max_nmn_verifications_per_day)
    RolePermission.objects.bulk_create([
        RolePermission(role=clone, permission=p) for p in src.permissions.all()])
    log_action(request.user, "role.created", "roles", f"Role '{name}' cloned from '{src.name}'")
    messages.success(request, f"Cloned '{src.name}' as '{name}'.")
    return redirect("role-edit", role_id=clone.id)


@require_permission("roles.assign")
def user_roles(request):
    if request.method == "POST":
        target = get_object_or_404(User, pk=request.POST.get("user_id"))
        role_ids = set(request.POST.getlist("roles"))
        before = set(target.user_roles.values_list("role__name", flat=True))
        UserRole.objects.filter(user=target).delete()
        for rid in role_ids:
            UserRole.objects.get_or_create(user=target, role_id=rid,
                                           defaults={"assigned_by": request.user})
        after = set(Role.objects.filter(id__in=role_ids).values_list("name", flat=True))
        log_action(request.user, "user.role_assigned", "roles",
                  f"Roles for '{target.username}' changed from {sorted(before)} to {sorted(after)}")
        messages.success(request, f"Updated roles for {target.username}.")
        return redirect("user-roles")

    users = User.objects.all().prefetch_related("user_roles__role").order_by("username")
    all_roles = Role.objects.all()
    return render(request, "rbac/user_roles.html", {
        "nav": "roles", "users": users, "all_roles": all_roles,
    })
