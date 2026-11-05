# apps/rbac/context_processors.py
"""Template context processors for RBAC.

Two processors are registered in settings.TEMPLATES:
  - permissions          -> exposes `perms_set` (UI permission gating)
  - pending_activations  -> exposes `pending_activation_count` (navbar dot)
"""
from __future__ import annotations

from .permissions import user_permission_codes


def permissions(request):
    """Exposes `perms_set` (a set of codenames, e.g. {"verification.execute"})
    to every template, so UI elements can hide themselves per-permission:
        {% if "schedules.cancel" in perms_set %}...{% endif %}
    This governs UI visibility only — the real enforcement is server-side
    in apps.rbac.decorators.require_permission on each view."""
    user = getattr(request, "user", None)
    return {"perms_set": user_permission_codes(user) if user else set()}


def pending_activations(request):
    """`pending_activation_count` powers the notification dot on the navbar
    "Users" link, so admins see at a glance that self-registered accounts are
    waiting to be activated — without opening the page."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {"pending_activation_count": 0}
    # Only surface the dot to people who can actually act on it.
    codes = user_permission_codes(user)
    can_see = (
        getattr(user, "is_superuser", False)
        or "users.activate" in codes
        or "users.create" in codes
        or "users.edit" in codes
        or "roles.assign" in codes
    )
    if not can_see:
        return {"pending_activation_count": 0}
    from apps.accounts.models import User
    return {"pending_activation_count": User.objects.filter(is_active=False).count()}
