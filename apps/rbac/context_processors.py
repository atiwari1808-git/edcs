from .permissions import user_permission_codes


def permissions(request):
    """Exposes `perms_set` (a set of codenames, e.g. {"verification.execute"})
    to every template, so UI elements can hide themselves per-permission:
        {% if "schedules.cancel" in perms_set %}...{% endif %}
    This governs UI visibility only — the real enforcement is server-side
    in apps.rbac.decorators.require_permission on each view."""
    user = getattr(request, "user", None)
    return {"perms_set": user_permission_codes(user) if user else set()}
