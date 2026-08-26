"""All app-originated email rides the internal SMTP relay (or the console
backend in dev).
Meeting INVITATIONS are NOT sent from here — Exchange sends those
automatically when the Graph event is created."""

from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings
from apps.adminconfig.models import EmailTemplate

# ── Low-level helpers ─────────────────────────────────────────────────────

def send_templated(key, to, ctx):
    tmpl = EmailTemplate.objects.filter(key=key).first()
    if not tmpl:
        return
    subject, body = tmpl.render(**ctx)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
              [t for t in to if t], fail_silently=False)

def _safe_send(subject, html_body, to):
    """Send an HTML email, falling back silently on error."""
    try:
        plain = (html_body
                 .replace("<br>", "\n").replace("</p>", "\n\n")
                 .replace("</li>", "\n").replace("</div>", "\n"))
        import re
        plain = re.sub(r"<[^>]+>", "", plain).strip()

        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[t for t in to if t],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()
    except Exception:
        pass

def _site_url():
    return getattr(settings, "SITE_URL", "").rstrip("/")

def _email_wrapper(title: str, accent_colour: str, body_html: str) -> str:
    """Wrap content in a clean Ericsson-branded email shell."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Arial,sans-serif;color:#1a2332}}
  .wrap{{max-width:620px;margin:32px auto;background:#fff;border-radius:12px;
         overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)}}
  .hdr{{background:{accent_colour};padding:28px 32px}}
  .hdr h1{{margin:0;font-size:1.2rem;font-weight:700;color:#fff;letter-spacing:.3px}}
  .hdr p{{margin:6px 0 0;font-size:.85rem;color:rgba(255,255,255,.85)}}
  .body{{padding:28px 32px}}
  .kv-row{{display:flex;gap:12px;margin-bottom:10px;align-items:baseline}}
  .kv-label{{min-width:140px;font-size:.78rem;font-weight:600;
             color:#6b7a8d;text-transform:uppercase;letter-spacing:.4px}}
  .kv-val{{font-size:.9rem;color:#1a2332;font-weight:500}}
  .badge{{display:inline-block;padding:3px 10px;border-radius:20px;
          font-size:.78rem;font-weight:700;letter-spacing:.3px}}
  .badge-pass{{background:#d6ead7;color:#1e6b2e}}
  .badge-fail{{background:#ffd7d7;color:#9b1c1c}}
  .badge-warn{{background:#fff3cd;color:#7d5a00}}
  .section-title{{font-size:.8rem;font-weight:700;color:#6b7a8d;
                  text-transform:uppercase;letter-spacing:.5px;
                  margin:20px 0 10px;border-bottom:1px solid #e8edf2;padding-bottom:6px}}
  .detail-box{{background:#f8fafc;border-radius:8px;padding:14px 18px;
               margin-bottom:16px;border-left:3px solid {accent_colour}}}
  .detail-box ul{{margin:0;padding-left:18px}}
  .detail-box li{{font-size:.875rem;color:#3a4a5c;margin-bottom:4px}}
  .cta{{display:inline-block;margin-top:18px;padding:10px 22px;
        background:{accent_colour};color:#fff;border-radius:8px;
        text-decoration:none;font-weight:600;font-size:.9rem}}
  .footer{{background:#f4f6f9;padding:16px 32px;font-size:.75rem;
           color:#8a96a3;border-top:1px solid #e8edf2}}
  .divider{{height:1px;background:#e8edf2;margin:18px 0}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>EDCS-Gate · Handover Scheduler</h1>
    <p>{title}</p>
  </div>
  <div class="body">
    {body_html}
  </div>
  <div class="footer">
    This is an automated notification from EDCS-Gate.
    Do not reply to this email. &nbsp;|&nbsp; Ericsson Internal
  </div>
</div>
</body>
</html>"""

def _scan_summary_rows(run) -> str:
    """Build KV detail rows for a ValidationRun."""
    at = run.automation_type
    at_display = at.display_name if at else "—"
    rows = f"""
    <div class="kv-row"><span class="kv-label">Tool</span>
      <span class="kv-val">{run.tool.display_name}</span></div>
    <div class="kv-row"><span class="kv-label">Automation Type</span>
      <span class="kv-val">{at_display}</span></div>
    <div class="kv-row"><span class="kv-label">Customer</span>
      <span class="kv-val">{getattr(run, 'customer_name', '') or '—'}</span></div>
    <div class="kv-row"><span class="kv-label">Automation Name</span>
      <span class="kv-val">{getattr(run, 'automation_name', '') or '—'}</span></div>
    <div class="kv-row"><span class="kv-label">JIRA ID</span>
      <span class="kv-val">{run.jira_id}</span></div>
    <div class="kv-row"><span class="kv-label">Initiated by</span>
      <span class="kv-val">{run.requested_by.get_full_name() or run.requested_by.username}</span></div>
    <div class="kv-row"><span class="kv-label">Completed at</span>
      <span class="kv-val">{run.finished_at.strftime('%Y-%m-%d %H:%M UTC') if run.finished_at else '—'}</span></div>
    """
    return rows

def _scanner_results_html(run) -> str:
    """Build scanner result detail boxes."""
    summary = run.summary or {}
    passed  = summary.get("passed", 0)
    failed  = summary.get("failed", 0)
    warns   = summary.get("warnings", 0)
    boxes   = ""
    for r in run.results.all():
        status_cls = "badge-pass" if r.status == "PASSED" else "badge-fail"
        label      = "ERIDOC Documents" if r.scanner == "ERIDOC" else "Bitbucket Code"
        items      = ""
        if r.failed_checks:
            items += "<li><b>Failed checks:</b> " + ", ".join(
                str(c) for c in r.failed_checks[:10]) + "</li>"
        if r.missing_documents:
            items += "<li><b>Missing documents:</b> " + ", ".join(
                str(d) for d in r.missing_documents[:10]) + "</li>"
        if r.blank_documents:
            items += "<li><b>Blank documents:</b> " + ", ".join(
                str(d) for d in r.blank_documents[:10]) + "</li>"
        if r.warnings:
            items += "<li><b>Warnings:</b> " + ", ".join(
                str(w) for w in r.warnings[:5]) + "</li>"
        if not items:
            items = "<li>All checks passed ✓</li>"
        boxes += f"""
        <div class="detail-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:600;font-size:.9rem">{label}</span>
            <span class="badge {status_cls}">{r.status}</span>
          </div>
          <ul>{items}</ul>
        </div>"""

    stats_html = f"""
    <div style="display:flex;gap:16px;margin:16px 0;flex-wrap:wrap">
      <div style="background:#d6ead7;border-radius:8px;padding:10px 18px;text-align:center">
        <div style="font-size:1.4rem;font-weight:700;color:#1e6b2e">{passed}</div>
        <div style="font-size:.75rem;color:#1e6b2e;font-weight:600">Passed</div>
      </div>
      <div style="background:#ffd7d7;border-radius:8px;padding:10px 18px;text-align:center">
        <div style="font-size:1.4rem;font-weight:700;color:#9b1c1c">{failed}</div>
        <div style="font-size:.75rem;color:#9b1c1c;font-weight:600">Failed</div>
      </div>
      <div style="background:#fff3cd;border-radius:8px;padding:10px 18px;text-align:center">
        <div style="font-size:1.4rem;font-weight:700;color:#7d5a00">{warns}</div>
        <div style="font-size:.75rem;color:#7d5a00;font-weight:600">Warnings</div>
      </div>
    </div>"""
    return stats_html + boxes

# ── Account & booking notifications ──────────────────────────────────────

def registration_received(user):
    html = _email_wrapper(
        title="Account registration received",
        accent_colour="#1C3C5A",
        body_html=f"""
        <p>Hi <b>{user.get_full_name() or user.username}</b>,</p>
        <p>Your account has been successfully created and is currently
        <b>awaiting administrator activation</b>.
        You will receive another email as soon as it is active.</p>
        <div class="divider"></div>
        <p style="font-size:.85rem;color:#6b7a8d">
          If you did not register for EDCS-Gate, please ignore this email.
        </p>""",
    )
    _safe_send("EDCS-Gate — Registration received", html, [user.email])

def account_activated(user):
    html = _email_wrapper(
        title="Your account is now active",
        accent_colour="#1e6b2e",
        body_html=f"""
        <p>Hi <b>{user.get_full_name() or user.username}</b>,</p>
        <p>Great news — your EDCS-Gate account is now <b>active</b>.
        You can sign in and start a verification.</p>
        <a class="cta" href="{_site_url()}/login/">Sign in now</a>""",
    )
    _safe_send("EDCS-Gate — Account activated", html, [user.email])

# ── Scan completion emails (type-aware) ───────────────────────────────────

def _get_recipients(run) -> list[str]:
    """Return deduped list: scanning user + configured notification addresses."""
    recipients = [run.requested_by.email] if run.requested_by else []
    at = run.automation_type
    if at:
        recipients += at.get_notification_email_list()
    return list(dict.fromkeys(e for e in recipients if e))

def send_doconly_complete_email(run):
    """Sent for Healthcheck / Backup on PASS — no meeting required."""
    at        = run.automation_type
    at_name   = at.display_name if at else "Document Verification"
    recipients = _get_recipients(run)
    report_url = f"{_site_url()}/validations/{run.id}/report/"

    body = f"""
    <p>Hi team,</p>
    <p>The <b>{at_name}</b> document verification for
    <b>{run.jira_id}</b> has completed successfully.
    <span class="badge badge-pass">PASSED</span></p>
    <p style="background:#e8f5e9;border-radius:8px;padding:12px 16px;
              border-left:4px solid #2e7d32;color:#1b5e20">
      <b>✅ No meeting scheduling required</b> for this automation type.
      The verification report is available below.
    </p>
    <div class="section-title">Scan Details</div>
    {_scan_summary_rows(run)}
    <div class="section-title">Scanner Results</div>
    {_scanner_results_html(run)}
    <a class="cta" href="{report_url}">View Full Report</a>"""

    html = _email_wrapper(
        title=f"{at_name} Verification — PASSED ✅",
        accent_colour="#2e7d32",
        body_html=body,
    )
    _safe_send(
        f"[EDCS-Gate] {at_name} PASSED — {run.jira_id} — No meeting needed",
        html, recipients,
    )

def send_execution_passed_email(run):
    """Sent for Execution type on PASS — prompts user to schedule meeting."""
    at        = run.automation_type
    at_name   = at.display_name if at else "Execution"
    recipients = _get_recipients(run)
    report_url    = f"{_site_url()}/validations/{run.id}/report/"
    scheduler_url = f"{_site_url()}/scheduler/?run_id={run.id}"

    body = f"""
    <p>Hi team,</p>
    <p>The <b>{at_name}</b> document verification for
    <b>{run.jira_id}</b> has <b>passed</b> all checks.
    <span class="badge badge-pass">PASSED</span></p>
    <p style="background:#e3f2fd;border-radius:8px;padding:12px 16px;
              border-left:4px solid #1565c0;color:#0d47a1">
      <b>📅 Next step:</b> Please proceed to the Handover Scheduler
      to book your handover call slot.
    </p>
    <div class="section-title">Scan Details</div>
    {_scan_summary_rows(run)}
    <div class="section-title">Scanner Results</div>
    {_scanner_results_html(run)}
    <div style="display:flex;gap:12px;margin-top:20px;flex-wrap:wrap">
      <a class="cta" href="{scheduler_url}"
         style="background:#1565c0">📅 Schedule Handover Call</a>
      <a class="cta" href="{report_url}"
         style="background:#455a64">View Report</a>
    </div>"""

    html = _email_wrapper(
        title=f"{at_name} Verification — PASSED ✅ — Schedule your call",
        accent_colour="#1565c0",
        body_html=body,
    )
    _safe_send(
        f"[EDCS-Gate] Verification PASSED — {run.jira_id} — Schedule your handover call",
        html, recipients,
    )

def send_scan_failed_email(run):
    """Sent for any type on FAILED / ERROR."""
    at        = run.automation_type
    at_name   = at.display_name if at else "Verification"
    recipients = _get_recipients(run)
    report_url = f"{_site_url()}/validations/{run.id}/report/"
    verify_url = f"{_site_url()}/verify/"

    body = f"""
    <p>Hi team,</p>
    <p>The <b>{at_name}</b> document verification for
    <b>{run.jira_id}</b> did <b>not pass</b>.
    <span class="badge badge-fail">{run.status}</span></p>
    <p style="background:#fff5f5;border-radius:8px;padding:12px 16px;
              border-left:4px solid #c62828;color:#7f1d1d">
      <b>❌ Action required:</b> Please review the report below, correct
      all identified issues, and re-run the verification before scheduling.
    </p>
    <div class="section-title">Scan Details</div>
    {_scan_summary_rows(run)}
    <div class="section-title">Scanner Results &amp; Issues Found</div>
    {_scanner_results_html(run)}
    <div style="display:flex;gap:12px;margin-top:20px;flex-wrap:wrap">
      <a class="cta" href="{report_url}"
         style="background:#c62828">View Detailed Report</a>
      <a class="cta" href="{verify_url}"
         style="background:#455a64">Re-run Verification</a>
    </div>"""

    html = _email_wrapper(
        title=f"{at_name} Verification — {run.status} ❌",
        accent_colour="#c62828",
        body_html=body,
    )
    _safe_send(
        f"[EDCS-Gate] Verification {run.status} — {run.jira_id} — Action required",
        html, recipients,
    )

# Keep the old plain-text function as a fallback alias
def verification_result(user, tool, jira_id, status):
    """Legacy plain-text fallback (kept for compatibility)."""
    _safe_send(
        f"Verification {status} — {jira_id}",
        f"<p>Hi {user.get_full_name() or user.username},</p>"
        f"<p>Your {tool} verification for {jira_id} finished with status: "
        f"<b>{status}</b>.</p>",
        [user.email],
    )

