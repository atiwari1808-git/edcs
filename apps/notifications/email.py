"""All app-originated email rides the internal SMTP relay (or the console
backend in dev). Meeting INVITATIONS are NOT sent from here — Exchange
sends those automatically when the Graph event is created."""
from django.core.mail import send_mail
from django.conf import settings
from apps.adminconfig.models import EmailTemplate


def send_templated(key, to, ctx):
    tmpl = EmailTemplate.objects.filter(key=key).first()
    if not tmpl:
        return
    subject, body = tmpl.render(**ctx)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
              [t for t in to if t], fail_silently=False)


# ── Account & booking notifications (Handover-Scheduler parity) ─────
def _safe_send(subject, body, to):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                  [t for t in to if t], fail_silently=True)
    except Exception:
        pass


def registration_received(user):
    _safe_send("Handover Scheduler — registration received",
        f"Hi {user.get_full_name() or user.username},\n\n"
        "Your account has been created and is awaiting administrator "
        "activation. You'll receive another email once it's active.\n",
        [user.email])


def account_activated(user):
    _safe_send("Handover Scheduler — account activated",
        f"Hi {user.get_full_name() or user.username},\n\n"
        "Your account is now active — you can sign in and start a handover.\n",
        [user.email])


def verification_result(user, tool, jira_id, status):
    _safe_send(f"Verification {status} — {jira_id}",
        f"Hi {user.get_full_name() or user.username},\n\n"
        f"Your {tool} verification for {jira_id} finished with status: "
        f"{status}.\nOpen Handover Scheduler for the detailed report.\n",
        [user.email])
