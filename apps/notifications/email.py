"""All app-originated email rides the internal SMTP relay (or the console
backend in dev).

Meeting INVITATIONS are NOT sent from here — Exchange sends those automatically
when the Graph event is created.

Rendering note: these emails are built with a TABLE-BASED layout, `bgcolor`
attributes and fully inline styles so they render correctly in the classic
Outlook (Word) engine as well as Outlook-on-the-web / mobile clients. Do NOT
switch back to <div>+CSS-background layouts — the Word engine drops them.
"""
from __future__ import annotations
import re
from html import escape

from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings
from apps.adminconfig.models import EmailTemplate, HandoverFollowupConfig, HandoverFollowupConfig
from apps.reports.context import humanize_fix

# ── Brand palette ─────────────────────────────────────────────────────────
BRAND        = "#0c2340"   # Ericsson deep blue
INK          = "#1a1f2b"
MUTE         = "#5b6472"
LINE         = "#dfe4ec"
PAGE_BG      = "#eef1f6"
CARD_BG      = "#ffffff"
ROW_ALT      = "#f5f7fb"

PASS_C       = "#1b7a34"
FAIL_C       = "#b71c1c"
ERROR_C      = "#a5560a"
WARN_C       = "#a5560a"

_SEV = {
    "CRITICAL": ("#b71c1c", "#fdecea"),
    "HIGH":     ("#c62828", "#fdecea"),
    "MEDIUM":   ("#a5560a", "#fff4e5"),
    "LOW":      ("#1565c0", "#e8f0fe"),
    "INFO":     ("#555555", "#eef1f5"),
}

FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,"
        "Arial,sans-serif")


# ── Low-level helpers ───────────────────────────────────────────────────────
def send_templated(key, to, ctx):
    tmpl = EmailTemplate.objects.filter(key=key).first()
    if not tmpl:
        return
    subject, body = tmpl.render(**ctx)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
              [t for t in to if t], fail_silently=False)


def _plain_from_html(html_body: str) -> str:
    txt = re.sub(r"(?is)<(br|/tr|/p|/div|/h[1-6])\s*/?>", "\n", html_body)
    txt = re.sub(r"(?is)<[^>]+>", "", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _safe_send(subject, html_body, to, run=None):
    """Send an HTML email, falling back silently on error.

    When `run` has a rendered PDF report, it is attached automatically.
    """
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=_plain_from_html(html_body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[t for t in to if t],
        )
        msg.attach_alternative(html_body, "text/html")

        # Always attach the full PDF report when available.
        pdf = getattr(run, "pdf_file", None) if run is not None else None
        if pdf:
            try:
                pdf.open("rb")
                data = pdf.read()
                pdf.close()
                if data:
                    jira = getattr(run, "jira_id", "report")
                    msg.attach(f"EDCS-Gate-Report-{jira}.pdf",
                               data, "application/pdf")
            except Exception:
                pass  # attachment must never block the notification

        msg.send()
    except Exception:
        pass


def _site_url():
    return getattr(settings, "SITE_URL", "").rstrip("/")


# ── Reusable Outlook-safe building blocks ───────────────────────────────────
def _btn(label: str, href: str, bg: str, primary: bool = True) -> str:
    """A bulletproof table-cell button (renders in classic Outlook)."""
    if not href:
        return ""
    txt_color = "#ffffff" if primary else BRAND
    border = bg if primary else "#c3ccda"
    fill = bg if primary else "#ffffff"
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" border="0"
           style="border-collapse:collapse;margin:4px 8px 4px 0;display:inline-block;">
      <tr>
        <td bgcolor="{fill}" align="center"
            style="border:1px solid {border};border-radius:6px;">
          <a href="{escape(href)}"
             style="display:inline-block;padding:11px 22px;font-family:{FONT};
                    font-size:14px;font-weight:700;line-height:1;color:{txt_color};
                    text-decoration:none;">{escape(label)}</a>
        </td>
      </tr>
    </table>"""


def _status_pill(text: str, color: str, bg: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'border="0" style="display:inline-block;border-collapse:collapse;">'
            f'<tr><td bgcolor="{bg}" style="padding:5px 14px;border-radius:20px;'
            f'font-family:{FONT};font-size:13px;font-weight:800;color:{color};'
            f'letter-spacing:.3px;">{escape(text)}</td></tr></table>')


def _kv_rows(pairs) -> str:
    rows = ""
    for i, (k, v) in enumerate(pairs):
        bg = CARD_BG if i % 2 == 0 else ROW_ALT
        rows += f"""
        <tr>
          <td bgcolor="{bg}" width="180"
              style="padding:9px 14px;border-bottom:1px solid {LINE};
                     font-family:{FONT};font-size:13px;font-weight:700;
                     color:{MUTE};vertical-align:top;">{escape(str(k))}</td>
          <td bgcolor="{bg}"
              style="padding:9px 14px;border-bottom:1px solid {LINE};
                     font-family:{FONT};font-size:13px;color:{INK};
                     vertical-align:top;">{escape(str(v)) or '&mdash;'}</td>
        </tr>"""
    return (f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0" style="border-collapse:collapse;'
            f'border:1px solid {LINE};border-radius:8px;overflow:hidden;">'
            f'{rows}</table>')


def _sev_badge(sev: str) -> str:
    sev = (sev or "INFO").upper()
    color, bg = _SEV.get(sev, _SEV["INFO"])
    return (f'<span style="display:inline-block;padding:2px 9px;border-radius:'
            f'10px;background:{bg};color:{color};font-family:{FONT};'
            f'font-size:11px;font-weight:800;letter-spacing:.3px;">{escape(sev)}'
            f'</span>')


def _findings_table(items, kind_label) -> str:
    """Render a list of finding dicts as a readable table (not raw dicts)."""
    head = f"""
    <tr>
      <td bgcolor="{BRAND}" style="padding:7px 10px;font-family:{FONT};
          font-size:11px;font-weight:800;color:#ffffff;letter-spacing:.4px;">
          SEVERITY</td>
      <td bgcolor="{BRAND}" style="padding:7px 10px;font-family:{FONT};
          font-size:11px;font-weight:800;color:#ffffff;letter-spacing:.4px;">
          LOCATION</td>
      <td bgcolor="{BRAND}" style="padding:7px 10px;font-family:{FONT};
          font-size:11px;font-weight:800;color:#ffffff;letter-spacing:.4px;">
          ISSUE &amp; SUGGESTED FIX</td>
    </tr>"""
    body = ""
    shown = items[:20]
    for i, it in enumerate(shown):
        bg = CARD_BG if i % 2 == 0 else ROW_ALT
        f = escape(str(it.get("file", "") or ""))
        ln = it.get("line")
        loc = f + (f":{ln}" if ln not in (None, "", 0) else "")
        title = escape(str(it.get("title", "") or it.get("code", "") or "Issue"))
        detail = escape(str(it.get("detail", "") or ""))
        rec = escape(humanize_fix(it))
        issue = f'<strong style="color:{INK};">{title}</strong>'
        if detail:
            issue += f'<br><span style="color:{INK};">{detail}</span>'
        if rec:
            issue += (f'<br><span style="color:{PASS_C};font-size:12px;">'
                      f'&#10003; Fix: {rec}</span>')
        body += f"""
        <tr>
          <td bgcolor="{bg}" width="90" style="padding:9px 10px;border-bottom:
              1px solid {LINE};font-family:{FONT};font-size:12px;
              vertical-align:top;">{_sev_badge(it.get('severity'))}</td>
          <td bgcolor="{bg}" width="150" style="padding:9px 10px;border-bottom:
              1px solid {LINE};font-family:{FONT};font-size:12px;color:{INK};
              vertical-align:top;word-break:break-all;">{loc or '&mdash;'}</td>
          <td bgcolor="{bg}" style="padding:9px 10px;border-bottom:1px solid
              {LINE};font-family:{FONT};font-size:12px;line-height:1.5;
              vertical-align:top;">{issue}</td>
        </tr>"""
    more = ""
    if len(items) > len(shown):
        more = (f'<tr><td colspan="3" style="padding:8px 10px;font-family:{FONT};'
                f'font-size:12px;color:{MUTE};font-style:italic;">'
                f'+ {len(items) - len(shown)} more {escape(kind_label)} '
                f'— see the attached PDF report for the full list.</td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0" style="border-collapse:collapse;'
            f'border:1px solid {LINE};border-radius:8px;overflow:hidden;'
            f'margin:6px 0 2px;">{head}{body}{more}</table>')


def _error_box(message: str) -> str:
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           border="0" style="border-collapse:collapse;margin:6px 0;">
      <tr>
        <td bgcolor="#fff4e5" style="padding:12px 14px;border:1px solid #f0c98a;
            border-left:4px solid {ERROR_C};border-radius:6px;font-family:{FONT};
            font-size:13px;line-height:1.55;color:#5a3a08;">
          <strong style="color:{ERROR_C};">This check could not be completed.</strong><br>
          {escape(message)}
        </td>
      </tr>
    </table>"""


def _ok_box() -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0" style="border-collapse:collapse;'
            f'margin:6px 0;"><tr><td bgcolor="#eaf6ee" style="padding:11px 14px;'
            f'border:1px solid #b7e0c2;border-radius:6px;font-family:{FONT};'
            f'font-size:13px;color:{PASS_C};font-weight:700;">'
            f'&#10003; All checks passed — no issues found.</td></tr></table>')


def _scanner_blocks(run) -> str:
    """One block per scanner: name + status pill, then error box / findings /
    all-passed — never a raw dict dump."""
    out = ""
    for r in run.results.all():
        label = "ERIDOC Documents" if r.scanner == "ERIDOC" else "Bitbucket Code"
        st = (r.status or "").upper()
        if st == "PASSED":
            pill = _status_pill("PASSED", PASS_C, "#eaf6ee")
        elif st == "ERROR":
            pill = _status_pill("COULD NOT COMPLETE", ERROR_C, "#fff4e5")
        elif st in ("RUNNING", "PENDING"):
            pill = _status_pill("DID NOT FINISH", ERROR_C, "#fff4e5")
        elif st == "CANCELLED":
            pill = _status_pill("CANCELLED", MUTE, "#eef1f5")
        else:
            pill = _status_pill("FAILED", FAIL_C, "#fdecea")

        inner = ""
        if st == "ERROR":
            inner = _error_box(r.error_message or
                               "The scan did not complete. Please re-run the "
                               "verification.")
        elif st in ("RUNNING", "PENDING"):
            inner = _error_box("The scan did not finish. Please re-run the "
                               "verification.")
        else:
            if r.missing_documents:
                inner += _findings_table(r.missing_documents, "missing documents")
            if r.blank_documents:
                inner += _findings_table(r.blank_documents, "blank documents")
            if r.failed_checks:
                inner += _findings_table(r.failed_checks, "failed checks")
            if r.warnings:
                inner += _findings_table(r.warnings, "warnings")
            if not inner:
                inner = _ok_box()

        out += f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               border="0" style="border-collapse:collapse;margin:0 0 16px;
               border:1px solid {LINE};border-radius:8px;">
          <tr>
            <td style="padding:12px 14px;border-bottom:1px solid {LINE};
                font-family:{FONT};">
              <table role="presentation" width="100%" cellpadding="0"
                     cellspacing="0" border="0"><tr>
                <td style="font-family:{FONT};font-size:15px;font-weight:800;
                    color:{BRAND};">{escape(label)}</td>
                <td align="right">{pill}</td>
              </tr></table>
            </td>
          </tr>
          <tr><td style="padding:10px 14px 4px;">{inner}</td></tr>
        </table>"""
    return out


def _summary_stats(run) -> str:
    s = run.summary or {}
    p, f, w = s.get("passed", 0), s.get("failed", 0), s.get("warnings", 0)
    cell = ("padding:14px 8px;text-align:center;font-family:%s;border:1px "
            "solid %s;" % (FONT, LINE))
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           border="0" style="border-collapse:collapse;margin:2px 0 18px;">
      <tr>
        <td width="33%" bgcolor="#eaf6ee" style="{cell}border-radius:8px 0 0 8px;">
          <div style="font-size:26px;font-weight:800;color:{PASS_C};">{p}</div>
          <div style="font-size:12px;font-weight:700;color:{MUTE};">PASSED</div>
        </td>
        <td width="33%" bgcolor="#fdecea" style="{cell}">
          <div style="font-size:26px;font-weight:800;color:{FAIL_C};">{f}</div>
          <div style="font-size:12px;font-weight:700;color:{MUTE};">FAILED</div>
        </td>
        <td width="33%" bgcolor="#fff4e5" style="{cell}border-radius:0 8px 8px 0;">
          <div style="font-size:26px;font-weight:800;color:{WARN_C};">{w}</div>
          <div style="font-size:12px;font-weight:700;color:{MUTE};">WARNINGS</div>
        </td>
      </tr>
    </table>"""


def _shell(title: str, subtitle: str, accent: str, body_html: str) -> str:
    """Full Outlook-safe email document."""
    return f"""<!DOCTYPE html>
<html xmlns:v="urn:schemas-microsoft-com:vml"
      xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<!--[if mso]><style>table,td{{border-collapse:collapse;
  font-family:Arial,Helvetica,sans-serif !important;}}</style><![endif]-->
</head>
<body style="margin:0;padding:0;background:{PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       border="0" bgcolor="{PAGE_BG}" style="border-collapse:collapse;
       background:{PAGE_BG};">
  <tr><td align="center" style="padding:24px 12px;">
    <!--[if mso]><table role="presentation" width="640" cellpadding="0"
        cellspacing="0" border="0"><tr><td><![endif]-->
    <table role="presentation" width="640" cellpadding="0" cellspacing="0"
           border="0" style="width:640px;max-width:640px;border-collapse:
           collapse;background:{CARD_BG};border-radius:12px;overflow:hidden;
           border:1px solid {LINE};">
      <!-- header -->
      <tr>
        <td bgcolor="{BRAND}" style="padding:22px 28px;font-family:{FONT};">
          <div style="font-size:19px;font-weight:800;color:#ffffff;
               letter-spacing:.2px;">EDCS-Gate &middot; Handover Scheduler</div>
        </td>
      </tr>
      <!-- accent title band -->
      <tr>
        <td bgcolor="{accent}" style="padding:16px 28px;font-family:{FONT};">
          <div style="font-size:16px;font-weight:800;color:#ffffff;">
            {escape(title)}</div>
          {f'<div style="font-size:13px;color:#eef3fb;margin-top:3px;">{escape(subtitle)}</div>' if subtitle else ''}
        </td>
      </tr>
      <!-- body -->
      <tr><td style="padding:22px 28px;font-family:{FONT};font-size:14px;
             line-height:1.6;color:{INK};">{body_html}</td></tr>
      <!-- footer -->
      <tr>
        <td bgcolor="{ROW_ALT}" style="padding:16px 28px;border-top:1px solid
            {LINE};font-family:{FONT};font-size:12px;color:{MUTE};
            line-height:1.5;">
          This is an automated notification from EDCS-Gate. Do not reply to this
          email. &nbsp;|&nbsp; Ericsson Internal
        </td>
      </tr>
    </table>
    <!--[if mso]></td></tr></table><![endif]-->
  </td></tr>
</table>
</body></html>"""


def _section_title(text: str) -> str:
    return (f'<div style="font-family:{FONT};font-size:14px;font-weight:800;'
            f'color:{BRAND};margin:18px 0 8px;padding-bottom:6px;'
            f'border-bottom:2px solid {LINE};">{escape(text)}</div>')


def _scan_detail_pairs(run):
    at = run.automation_type
    return [
        ("Tool", run.tool.display_name),
        ("Automation Type", at.display_name if at else ""),
        ("Customer", getattr(run, "customer_name", "") or ""),
        ("Automation Name", getattr(run, "automation_name", "") or ""),
        ("JIRA ID", run.jira_id),
        ("Initiated by", run.requested_by.get_full_name()
                         or run.requested_by.username),
        ("Completed at", run.finished_at.strftime("%Y-%m-%d %H:%M UTC")
                         if run.finished_at else ""),
    ]


# ── Account & booking notifications ─────────────────────────────────────────
def registration_received(user):
    body = f"""
      <p style="margin:0 0 12px;">Hi {escape(user.get_full_name() or user.username)},</p>
      <p style="margin:0 0 12px;">Your account has been successfully created and
      is currently awaiting administrator activation.</p>
      <p style="margin:0 0 12px;">You will receive another email as soon as it is
      active.</p>
      <p style="margin:0;color:{MUTE};font-size:13px;">If you did not register for
      EDCS-Gate, please ignore this email.</p>"""
    html = _shell("Account registration received", "", BRAND, body)
    _safe_send("EDCS-Gate — Registration received", html, [user.email])


def account_activated(user):
    body = f"""
      <p style="margin:0 0 12px;">Hi {escape(user.get_full_name() or user.username)},</p>
      <p style="margin:0 0 16px;">Great news — your EDCS-Gate account is now
      active. You can sign in and start a verification.</p>
      {_btn("Sign in now", _site_url() + "/", PASS_C)}"""
    html = _shell("Your account is now active", "", PASS_C, body)
    _safe_send("EDCS-Gate — Account activated", html, [user.email])


# ── Scan completion emails (type-aware) ─────────────────────────────────────
def _get_tool_recipients(run) -> list[str]:
    cfg = None
    if getattr(run, "tool", None):
        cfg = HandoverFollowupConfig.objects.filter(tool=run.tool, is_active=True).first()
    if not cfg:
        return []
    return list(dict.fromkeys(e for e in cfg.team_email_list() if e))

def _get_requester_recipient(run) -> list[str]:
    if run.requested_by and run.requested_by.email:
        return [run.requested_by.email]
    return []

def _get_recipients(run) -> list[str]:
    recipients = [run.requested_by.email] if run.requested_by else []
    at = run.automation_type
    if at:
        recipients += at.get_notification_email_list()
    return list(dict.fromkeys(e for e in recipients if e))


def send_doconly_complete_email(run):
    """Sent for Healthcheck / Backup on PASS — no meeting required."""
    at = run.automation_type
    at_name = at.display_name if at else "Document Verification"
    report_url = f"{_site_url()}/validations/{run.id}/report/"
    body = f"""
      <p style="margin:0 0 12px;">Hi team,</p>
      <p style="margin:0 0 14px;">The <strong>{escape(at_name)}</strong> document
      verification for <strong>{escape(run.jira_id)}</strong> has completed
      successfully. {_status_pill("PASSED", PASS_C, "#eaf6ee")}</p>
      <p style="margin:0 0 14px;">No meeting scheduling is required for this
      automation type. The full report is attached as a PDF.</p>
      {_section_title("Scan Details")}
      {_kv_rows(_scan_detail_pairs(run))}
      {_section_title("Results Summary")}
      {_summary_stats(run)}
      {_section_title("Scanner Results")}
      {_scanner_blocks(run)}
      <div style="margin-top:8px;">{_btn("View Full Report", report_url, BRAND)}</div>"""
    html = _shell(f"{at_name} Verification — PASSED", "No meeting needed",
                  PASS_C, body)
    _safe_send(
        f"[EDCS-Gate] {at_name} PASSED — {run.jira_id} — No meeting needed",
        html, _get_recipients(run), run=run)


def send_execution_passed_email(run):
    """Sent for Execution type on PASS — prompts the user to schedule."""
    at = run.automation_type
    at_name = at.display_name if at else "Execution"
    report_url    = f"{_site_url()}/validations/{run.id}/report/"
    scheduler_url = f"{_site_url()}/scheduler/?run_id={run.id}"
    body = f"""
      <p style="margin:0 0 12px;">Hi team,</p>
      <p style="margin:0 0 14px;">The <strong>{escape(at_name)}</strong> document
      verification for <strong>{escape(run.jira_id)}</strong> has passed all
      checks. {_status_pill("PASSED", PASS_C, "#eaf6ee")}</p>
      <p style="margin:0 0 14px;"><strong>Next step:</strong> please proceed to
      the Handover Scheduler to book your handover call slot. The full report is
      attached as a PDF.</p>
      {_section_title("Scan Details")}
      {_kv_rows(_scan_detail_pairs(run))}
      {_section_title("Results Summary")}
      {_summary_stats(run)}
      {_section_title("Scanner Results")}
      {_scanner_blocks(run)}
      <div style="margin-top:8px;">
        {_btn("Schedule Handover Call", scheduler_url, PASS_C)}
        {_btn("View Report", report_url, BRAND, primary=False)}
      </div>"""
    html = _shell(f"{at_name} Verification — PASSED", "Schedule your call",
                  "#1565c0", body)
    _safe_send(
        f"[EDCS-Gate] Verification PASSED — {run.jira_id} — Schedule your handover call",
        html, _get_recipients(run), run=run)


def send_scan_failed_email(run):
    """Sent for any type on FAILED / ERROR."""
    at = run.automation_type
    at_name = at.display_name if at else "Verification"
    report_url = f"{_site_url()}/validations/{run.id}/report/"
    verify_url = f"{_site_url()}/verify/"

    is_error = (run.status == "ERROR")
    if is_error:
        headline = ("did not complete because one or more checks could not run")
        note = ("<strong>Action required:</strong> one or more scans could not "
                "complete (see the reason under each scanner below), so the "
                "verification did not pass. Fix the issue and re-run.")
        accent = ERROR_C
        subtitle = "Could not complete — action required"
    else:
        headline = "did not pass"
        note = ("<strong>Action required:</strong> please review the issues below "
                "(and the attached PDF report), correct them, and re-run the "
                "verification before scheduling.")
        accent = FAIL_C
        subtitle = "Action required"

    body = f"""
      <p style="margin:0 0 12px;">Hi team,</p>
      <p style="margin:0 0 14px;">The <strong>{escape(at_name)}</strong> document
      verification for <strong>{escape(run.jira_id)}</strong> {headline}.
      {_status_pill(run.status, FAIL_C if not is_error else ERROR_C,
                    "#fdecea" if not is_error else "#fff4e5")}</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             border="0" style="border-collapse:collapse;margin:0 0 14px;">
        <tr><td bgcolor="#fdecea" style="padding:12px 14px;border-left:4px solid
            {accent};border-radius:6px;font-family:{FONT};font-size:13px;
            line-height:1.55;color:#5a1a1a;">{note}</td></tr>
      </table>
      {_section_title("Scan Details")}
      {_kv_rows(_scan_detail_pairs(run))}
      {_section_title("Results Summary")}
      {_summary_stats(run)}
      {_section_title("Scanner Results & Issues Found")}
      {_scanner_blocks(run)}
      <div style="margin-top:8px;">
        {_btn("View Detailed Report", report_url, BRAND)}
        {_btn("Re-run Verification", verify_url, BRAND, primary=False)}
      </div>"""
    html = _shell(f"{at_name} Verification — {run.status}", subtitle, accent, body)
    _safe_send(
        f"[EDCS-Gate] Verification {run.status} — {run.jira_id} — Action required",
        html, _get_recipients(run), run=run)


# Keep the old plain-text function as a fallback alias
def verification_result(user, tool, jira_id, status):
    """Legacy plain-text fallback (kept for compatibility)."""
    _safe_send(
        f"Verification {status} — {jira_id}",
        f"<p>Hi {escape(user.get_full_name() or user.username)},</p>"
        f"<p>Your {escape(tool)} verification for {escape(jira_id)} finished with "
        f"status: {escape(status)}.</p>",
        [user.email])
