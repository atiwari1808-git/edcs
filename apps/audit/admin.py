from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("ts", "actor", "action", "module", "method", "path", "status_code", "ip")
    list_filter = ("module", "action", "method")
    search_fields = ("path", "actor__username", "action", "module", "detail")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, r):  return False
    def has_change_permission(self, r, obj=None):  return False
    def has_delete_permission(self, r, obj=None):  return False
