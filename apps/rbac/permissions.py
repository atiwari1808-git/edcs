"""The full set of (module, action) permissions the app understands, plus
the check helpers used by decorators, templates, and views.

Adding a new module or action is a ONE-LINE change here (plus re-running
`seed_rbac`) — no other code changes, no new roles required. Existing
roles simply won't have the new permission until an admin grants it via
the Role Management UI.
"""

# (module, action, human description) — module order here also drives the
# grouping/order shown in the Role Management UI.
PERMISSION_CATALOGUE = [
    ("dashboard", "view", "View the dashboard"),

    ("verification", "view", "View verification page & history"),
    ("verification", "create", "Start a new verification run"),
    ("verification", "edit", "Edit verification metadata (e.g. customer name)"),
    ("verification", "delete", "Delete a verification run"),
    ("verification", "execute", "Run/terminate a validation scan"),

    ("reports", "view", "View validation reports"),
    ("reports", "download", "Download report PDFs"),
    ("reports", "export", "Export report/booking data (e.g. Excel)"),

    ("schedules", "view", "View the scheduler & bookings"),
    ("schedules", "create", "Book a handover call"),
    ("schedules", "edit", "Edit/reschedule a booking"),
    ("schedules", "delete", "Delete a booking record"),
    ("schedules", "cancel", "Cancel a scheduled meeting"),

    ("users", "view", "View user accounts"),
    ("users", "create", "Create/activate user accounts"),
    ("users", "edit", "Edit user accounts"),
    ("users", "delete", "Deactivate/delete user accounts"),

    ("roles", "view", "View roles & permissions"),
    ("roles", "create", "Create new roles"),
    ("roles", "edit", "Edit role permissions"),
    ("roles", "delete", "Delete roles"),
    ("roles", "assign", "Assign roles to users"),

    ("settings", "view", "View system settings (tools, templates, holidays)"),
    ("settings", "modify", "Modify system settings"),
]

# Starter roles, seeded once by `seed_rbac` and fully editable afterwards.
# Every existing user is migrated onto the role matching their legacy
# User.role value the first time this runs.
DEFAULT_ROLES = {
    "Admin": {
        "description": "Full access to every module, including role management.",
        "codenames": [f"{m}.{a}" for m, a, _ in PERMISSION_CATALOGUE],
        "legacy_role": "ADMIN",
    },
    "Scrum Master": {
        "description": "Runs validations, manages schedules and reports. No role/user administration.",
        "codenames": [
            "dashboard.view",
            "verification.view", "verification.create", "verification.execute",
            "reports.view", "reports.download", "reports.export",
            "schedules.view", "schedules.create", "schedules.edit", "schedules.cancel",
            "settings.view",
        ],
        "legacy_role": "SCRUM_MASTER",
    },
    "Developer": {
        "description": "Read-only access, may run validations if additionally granted.",
        "codenames": [
            "dashboard.view",
            "verification.view",
            "reports.view",
            "schedules.view",
        ],
        "legacy_role": None,
    },
    "Viewer": {
        "description": "Read-only access everywhere, cannot run or change anything.",
        "codenames": [
            "dashboard.view", "verification.view", "reports.view", "schedules.view",
        ],
        "legacy_role": "VIEWER",
    },
}


def user_permission_codes(user) -> set:
    """The full set of permission codenames this user effectively holds
    (union across every assigned role). Superusers implicitly hold every
    known permission — this is Django's standard admin escape hatch, kept
    separate from the app-level RBAC data model on purpose."""
    if not getattr(user, "is_authenticated", False):
        return set()
    if user.is_superuser:
        from .models import Permission
        return set(Permission.objects.values_list("codename", flat=True))
    from .models import Permission
    return set(
        Permission.objects.filter(rolepermission__role__user_roles__user=user)
        .values_list("codename", flat=True).distinct()
    )


def user_has_permission(user, codename: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    from .models import Permission
    return Permission.objects.filter(
        codename=codename, rolepermission__role__user_roles__user=user
    ).exists()
