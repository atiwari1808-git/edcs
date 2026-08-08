from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user. Fine-grained access is governed by the dynamic
    RBAC system (apps.rbac) via `roles` — NOT by the legacy `role` field
    below, which is kept only as a display label / self-registration
    default and is migrated onto a real Role the first time `seed_rbac`
    runs. Django admin access (the raw /admin/ site) is separately
    controlled by is_staff/is_superuser, unrelated to app-level RBAC."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        SCRUM_MASTER = "SCRUM_MASTER", "Scrum Master"
        VIEWER = "VIEWER", "Viewer"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SCRUM_MASTER,
                            help_text="Legacy display label; real permissions come from `roles`.")
    azure_oid = models.CharField(max_length=64, blank=True, default="",
                                 help_text="Entra ID object id (set on Graph sign-in)")
    roles = models.ManyToManyField("rbac.Role", through="rbac.UserRole",
                                   through_fields=("user", "role"),
                                   related_name="users", blank=True)

    def has_perm_code(self, codename: str) -> bool:
        from apps.rbac.permissions import user_has_permission
        return user_has_permission(self, codename)

    @property
    def is_admin_role(self):
        return self.is_superuser or self.has_perm_code("roles.assign")

    @property
    def can_validate(self):
        return self.has_perm_code("verification.execute")
