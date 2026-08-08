"""Dynamic RBAC schema.

Design: Permission is an atomic (module, action) capability, identified by
a stable `codename` ("module.action"). Role is an admin-editable named
bundle of permissions (RolePermission, plain M2M-through). A user can hold
multiple Roles (UserRole, through-table with assignment audit fields) —
their effective permission set is the UNION of every assigned role's
permissions. Nothing here is hardcoded: new modules/actions are just new
Permission rows (see PERMISSION_CATALOGUE in permissions.py, applied by
`seed_rbac`), and new roles are created entirely through the Role
Management UI with no code change required.
"""
from django.conf import settings
from django.db import models


class Permission(models.Model):
    """One atomic capability, e.g. module="verification", action="execute"."""
    module = models.CharField(max_length=40, db_index=True)
    action = models.CharField(max_length=40)
    codename = models.CharField(max_length=80, unique=True, editable=False)
    description = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["module", "action"]
        unique_together = [("module", "action")]

    def save(self, *args, **kwargs):
        self.codename = f"{self.module}.{self.action}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.codename


class Role(models.Model):
    """An admin-editable, named bundle of permissions. `is_system` only
    blocks DELETION of the three seeded starter roles (Admin/Scrum
    Master/Viewer) so the app can't be locked out of itself by accident —
    their permissions remain fully editable like any other role."""
    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=200, blank=True, default="")
    is_system = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, through="RolePermission",
                                         related_name="roles")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        unique_together = [("role", "permission")]


class UserRole(models.Model):
    """Who holds which role, and who granted it — the assignment itself is
    an auditable fact, independent of the general AuditLog trail."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE,
                             related_name="user_roles")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                    blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "role")]
