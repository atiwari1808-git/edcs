"""Dynamic RBAC views.

The `/manage/users/` route is now a single unified hub ("Users") that combines,
in one place:
  * Pending activations  — self-registered accounts awaiting approval.
  * Users & roles        — activate/deactivate and assign roles per user.
  * Roles                — create/edit/clone/delete role permission bundles.
  * Default role         — the role auto-granted on self-registration
                           (configurable, stored in AppSetting).

Granularity: activation is gated by the distinct `users.create` permission, so
an admin can let (say) a Scrum Master activate accounts WITHOUT granting the
broader `users.edit` / `users.delete` / `roles.assign` capabilities.
"""
from itertools import groupby

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.audit.log import log_action
from .decorators import require_permission
from .models import Permission, Role, RolePermission, UserRole

# AppSetting key that stores the self-registration default role name.
DEFAULT_ROLE_SETTING_KEY = "self_register_default_role"
DEFAULT_ROLE_FALLBACK = "Developer"


def _grouped_permissions():
    """Permissions grouped by module, in catalogue order, for the checkbox UI."""
    perms = list(Permission.objects.order_by("module", "action"))
    return [(module, list(group)) for module, group in groupby(perms, key=lambda p: p.module)]


def get_default_role():
    """The Role new self-registered users receive, honouring the admin setting."""
    from apps.adminconfig.models import AppSetting
    name = AppSetting.get(DEFAULT_ROLE_SETTING_KEY, DEFAULT_ROLE_FALLBACK)
    role = Role.objects.filter(name=name).first()
    if role:
        return role
    # Setting points at a deleted role → fall back safely to the least-privileged.
    return (Role.objects.filter(name=DEFAULT_ROLE_FALLBACK).first()
            or Role.objects.order_by("name").first())


# ---------------------------------------------------------------- role CRUD ---
@require_permission("roles.view")
def role_list(request):
    roles = Role.objects.prefetch_related("permissions").all()
    return render(request, "rbac/role_list.html", {"nav": "users", "roles": roles})


@require_permission("roles.create")
def role_create(request):
    if request.method == "POST":
        return _save_role(request, role=None)
    return render(request, "rbac/role_form.html", {
        "nav": "users", "role": None, "grouped_permissions": _grouped_permissions(),
        "checked": set(),
    })


@require_permission("roles.edit")
def role_edit(request, role_id):
    role = get_object_or_404(Role, pk=role_id)
    if request.method == "POST":
        return _save_role(request, role=role)
    checked = set(role.permissions.values_list("codename", flat=True))
    return render(request, "rbac/role_form.html", {
        "nav": "users", "role": role, "grouped_permissions": _grouped_permissions(),
        "checked": checked,
    })


def _parse_limit(raw):
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
    return redirect("user-roles")


@require_permission("roles.delete")
@require_POST
def role_delete(request, role_id):
    role = get_object_or_404(Role, pk=role_id)
    if role.is_system:
        messages.error(request, f"'{role.name}' is a starter role and can't be deleted "
                                "(you can still edit its permissions freely).")
        return redirect("user-roles")
    assigned = UserRole.objects.filter(role=role).count()
    if assigned:
        messages.error(request, f"Can't delete '{role.name}': {assigned} user(s) still "
                                "hold it. Reassign them first.")
        return redirect("user-roles")
    name = role.name
    role.delete()
    log_action(request.user, "role.deleted", "roles", f"Role '{name}' deleted")
    messages.success(request, f"Role '{name}' deleted.")
    return redirect("user-roles")


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


# ------------------------------------------------------- unified Users hub ---
def user_roles(request):
    """The unified Users hub: activations + user/role assignment + role mgmt."""
    # Reachable by anyone with a user/role-management capability — including a
    # role granted ONLY `users.activate` (activate-pending-registrations-only).
    _view_perms = ("users.view", "users.activate", "users.create",
                   "users.edit", "users.delete", "roles.view", "roles.assign")
    if not (request.user.is_superuser
            or any(request.user.has_perm_code(p) for p in _view_perms)):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if request.method == "POST":
        # Role assignment requires the assign permission specifically.
        if not (request.user.is_superuser or request.user.has_perm_code("roles.assign")):
            messages.error(request, "You don't have permission to assign roles.")
            return redirect("user-roles")
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

    pending = (User.objects.filter(is_active=False)
               .prefetch_related("user_roles__role").order_by("date_joined"))
    active_users = (User.objects.filter(is_active=True)
                    .prefetch_related("user_roles__role").order_by("username"))
    all_roles = Role.objects.prefetch_related("permissions").all()

    # Permission flags drive which controls the template renders.
    su = request.user.is_superuser
    can = request.user.has_perm_code
    return render(request, "rbac/user_roles.html", {
        "nav": "users",
        "pending_users": pending,
        "users": active_users,
        "all_roles": all_roles,
        "default_role": get_default_role(),
        "can_activate":   su or can("users.activate") or can("users.create"),
        "can_deactivate": su or can("users.delete"),
        "can_assign":     su or can("roles.assign"),
        "can_manage_roles": su or can("roles.edit") or can("roles.create"),
        "can_create_roles": su or can("roles.create"),
        "can_delete_roles": su or can("roles.delete"),
        "can_set_default":  su or can("roles.assign"),
    })


@require_permission("roles.assign")
@require_POST
def set_default_role(request):
    """Persist which role self-registered users receive by default."""
    from apps.adminconfig.models import AppSetting
    name = (request.POST.get("default_role") or "").strip()
    if not Role.objects.filter(name=name).exists():
        messages.error(request, "Pick an existing role as the default.")
        return redirect("user-roles")
    AppSetting.objects.update_or_create(
        key=DEFAULT_ROLE_SETTING_KEY,
        defaults={"value": name,
                  "description": "Role auto-granted to self-registered users."})
    log_action(request.user, "settings.modified", "roles",
               f"Default self-registration role set to '{name}'")
    messages.success(request, f"New self-registered users will now get the '{name}' role.")
    return redirect("user-roles")
