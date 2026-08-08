from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only trail of every authenticated mutating request, PLUS
    semantic application events (validation started, meeting cancelled,
    role updated, ...) logged explicitly via apps.audit.log.log_action().
    In production revoke UPDATE/DELETE grants on this table."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                              on_delete=models.SET_NULL)
    method = models.CharField(max_length=8, blank=True, default="")
    path = models.CharField(max_length=300, blank=True, default="")
    status_code = models.PositiveSmallIntegerField(default=0)
    ip = models.GenericIPAddressField(null=True)
    ts = models.DateTimeField(auto_now_add=True, db_index=True)

    # Semantic fields (blank for the generic HTTP-level rows the
    # middleware writes; populated for explicit log_action() calls).
    action = models.CharField(max_length=60, blank=True, default="", db_index=True)
    module = models.CharField(max_length=40, blank=True, default="", db_index=True)
    detail = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-ts"]
