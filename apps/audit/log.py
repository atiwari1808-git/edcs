"""Call this from any view/task at the moment a meaningful business event
happens (validation started, meeting cancelled, role updated, ...). This
is separate from — and in addition to — the AuditMiddleware's generic
per-request HTTP logging: that captures every mutating call automatically,
this captures WHAT happened in plain terms for a human reading the trail.
"""
from .models import AuditLog

# Actions used across the app — kept here as documentation, not an enum;
# any string is accepted so new modules never need a code change here.
#   validation.started / validation.stopped / validation.terminated
#   meeting.created / meeting.edited / meeting.cancelled
#   report.generated
#   schedule.modified
#   role.created / role.updated / role.deleted
#   permission.updated
#   user.role_assigned


def log_action(user, action: str, module: str, detail: str = ""):
    try:
        AuditLog.objects.create(actor=user if getattr(user, "is_authenticated", False) else None,
                                action=action, module=module, detail=detail[:4000])
    except Exception:
        pass  # auditing must never break the request
