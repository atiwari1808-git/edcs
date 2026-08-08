"""Seeds the full permission catalogue + starter roles, and migrates every
existing user's legacy `role` field onto a real Role assignment. Idempotent
— safe to re-run (uses get_or_create throughout); re-running does NOT
overwrite permissions an admin has since customized on a starter role,
since it only creates rows that don't already exist."""
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.rbac.models import Permission, Role, RolePermission, UserRole
from apps.rbac.permissions import PERMISSION_CATALOGUE, DEFAULT_ROLES


class Command(BaseCommand):
    def handle(self, *args, **opts):
        # 1) Permission catalogue
        created_perms = 0
        for module, action, desc in PERMISSION_CATALOGUE:
            _, created = Permission.objects.get_or_create(
                module=module, action=action, defaults={"description": desc})
            created_perms += created
        self.stdout.write(f"Permissions: {len(PERMISSION_CATALOGUE)} in catalogue, "
                          f"{created_perms} newly created.")

        # 2) Starter roles (created once; permissions only ADDED on re-run,
        #    never removed, so admin customization is never clobbered)
        role_objs = {}
        for name, spec in DEFAULT_ROLES.items():
            role, created = Role.objects.get_or_create(
                name=name, defaults={"description": spec["description"], "is_system": True})
            if created:
                self.stdout.write(f"Role created: {name}")
            role_objs[name] = role
            for codename in spec["codenames"]:
                try:
                    perm = Permission.objects.get(codename=codename)
                except Permission.DoesNotExist:
                    continue
                RolePermission.objects.get_or_create(role=role, permission=perm)

        # 3) Migrate existing users from the legacy CharField onto a real role
        legacy_map = {spec["legacy_role"]: name for name, spec in DEFAULT_ROLES.items()
                     if spec["legacy_role"]}
        migrated = 0
        for user in User.objects.all():
            role_name = legacy_map.get(user.role)
            if not role_name:
                continue
            role = role_objs[role_name]
            _, created = UserRole.objects.get_or_create(user=user, role=role)
            migrated += created
        self.stdout.write(f"Users migrated onto a real role: {migrated}")
        self.stdout.write(self.style.SUCCESS("RBAC seed complete."))
