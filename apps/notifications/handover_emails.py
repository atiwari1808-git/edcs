"""
Handover lifecycle notifications (additive, self-contained).

Reuses the existing branded shell + safe sender from apps.notifications.email
(_email_wrapper, _safe_send, _site_url) so these emails look identical to the
scan-completion emails already in production. Nothing in email.py is modified.

Four notices:
  * meeting_cancelled_notice(meeting, reason, actor)      -> all participants
  * meeting_rescheduled_notice(old_m, new_m, actor)       -> all participants
  * golive_reminder_notice(meeting, cfg)                  -> per-tool team (day 10)
  * escalation_notice(meeting, policy, cfg)               -> global managers (day 15)
"""
from datetime import date
from apps.notifications.email import _email_wrapper, _safe_send, _site_url


# ── helpers ────────────────────────────────────────────────────────────────
def _fmt_dt(dt):
    try:
        return dt.strftime("%d %b %Y, %H:%M %Z").strip()
    except Exception:
        return str(dt or "")


def _fmt_d(d):
    try:
        return d.strftime("%d %b %Y")
    except Exception:
        return str(d or "")


def _participants(meeting) -> list[str]:
    """Every human on the meeting: attendees (dev/SM/CC/required) + organizer."""
    emails = [a.email for a in meeting.attendees.all() if a.email]
    if meeting.organizer and meeting.organizer.email:
        emails.append(meeting.organizer.email)
    return list(dict.fromkeys(e.strip() for e in emails if e and e.strip()))


def _jira(meeting) -> str:
    return meeting.validation_run.jira_id if meeting.validation_run else ""


def _automation(meeting) -> str:
    return (meeting.validation_run.automation_name
            if meeting.validation_run else "") or ""


def _detail_rows(meeting) -> str:
    """KV detail block matching the house style used in email.py."""
    slot = meeting.slot.label if meeting.slot else ""
    b_date = _fmt_d(meeting.booking_date or (meeting.start_at.date()
                                             if meeting.start_at else None))
    return f"""
      <table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:14px">
        <tr><td style="padding:6px 10px;color:#5a6b7b;width:170px">Tool</td>
            <td style="padding:6px 10px;font-weight:600">{meeting.tool_key}</td></tr>
        <tr><td style="padding:6px 10px;color:#5a6b7b">JIRA ID</td>
            <td style="padding:6px 10px;font-weight:600">{_jira(meeting)}</td></tr>
        <tr><td style="padding:6px 10px;color:#5a6b7b">Automation</td>
            <td style="padding:6px 10px">{_automation(meeting)}</td></tr>
        <tr><td style="padding:6px 10px;color:#5a6b7b">Handover date</td>
            <td style="padding:6px 10px;font-weight:600">{b_date}</td></tr>
        <tr><td style="padding:6px 10px;color:#5a6b7b">Slot</td>
            <td style="padding:6px 10px">{slot}</td></tr>
        <tr><td style="padding:6px 10px;color:#5a6b7b">Organizer</td>
            <td style="padding:6px 10px">{meeting.organizer.email if meeting.organizer else ''}</td></tr>
      </table>
    """


# ── 1. cancellation notice (all participants) ────────────────────────────────
def meeting_cancelled_notice(meeting, reason: str = "", actor=None):
    to = _participants(meeting)
    if not to:
        return
    who = ""
    if actor is not None:
        who = actor.get_full_name() or actor.username
    reason_html = (f"""
        <p style="margin:14px 0 4px;color:#5a6b7b">Reason</p>
        <div style="padding:10px 14px;background:#fff4f4;border-left:3px solid #c62828;
                    border-radius:6px;font-size:14px">{reason}</div>"""
        if reason else "")
    body = f"""
      <p>Hi team,</p>
      <p>The following handover call has been <strong>cancelled</strong>
         {f'by {who}' if who else ''}. No further action is required for this
         meeting — the calendar invite is being withdrawn automatically.</p>
      {_detail_rows(meeting)}
      {reason_html}
      <p style="margin-top:16px;color:#5a6b7b;font-size:13px">
         If you believe this is a mistake, please contact the organizer to
         re-book the handover.</p>
    """
    html = _email_wrapper(
        title="Handover call cancelled",
        accent_colour="#c62828",
        body_html=body,
    )
    _safe_send(
        f"[EDCS-Gate] Handover CANCELLED — {_jira(meeting)} ({meeting.tool_key})",
        html, to,
    )


# ── 2. reschedule notice (all participants, old -> new) ──────────────────────
def meeting_rescheduled_notice(old_meeting, new_meeting, actor=None):
    # Notify everyone on either the old or the new meeting.
    to = list(dict.fromkeys(_participants(old_meeting) + _participants(new_meeting)))
    if not to:
        return
    who = ""
    if actor is not None:
        who = actor.get_full_name() or actor.username
    old_date = _fmt_d(old_meeting.booking_date or (old_meeting.start_at.date()
                      if old_meeting.start_at else None))
    old_slot = old_meeting.slot.label if old_meeting.slot else ""
    new_date = _fmt_d(new_meeting.booking_date or (new_meeting.start_at.date()
                      if new_meeting.start_at else None))
    new_slot = new_meeting.slot.label if new_meeting.slot else ""
    change = f"""
      <table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:14px">
        <tr>
          <td style="padding:8px 12px;background:#f4f6f9;border-radius:6px;color:#5a6b7b">
             Previous</td>
          <td style="padding:8px 12px;text-decoration:line-through;color:#9b1c1c">
             {old_date} · {old_slot}</td>
        </tr>
        <tr>
          <td style="padding:8px 12px;background:#eef7ee;border-radius:6px;color:#1e6b2e">
             New</td>
          <td style="padding:8px 12px;font-weight:700;color:#1e6b2e">
             {new_date} · {new_slot}</td>
        </tr>
      </table>
    """
    body = f"""
      <p>Hi team,</p>
      <p>The handover call for <strong>{_jira(new_meeting)}</strong>
         ({new_meeting.tool_key}) has been <strong>rescheduled</strong>
         {f'by {who}' if who else ''}. A fresh calendar invite for the new time
         is on its way — please discard the previous one.</p>
      {change}
      {_detail_rows(new_meeting)}
    """
    html = _email_wrapper(
        title="Handover call rescheduled",
        accent_colour="#1565c0",
        body_html=body,
    )
    _safe_send(
        f"[EDCS-Gate] Handover RESCHEDULED — {_jira(new_meeting)} "
        f"({new_meeting.tool_key}) → {new_date}",
        html, to,
    )


# ── 3. GO-live reminder (per-tool team, day 10) ──────────────────────────────
def golive_reminder_notice(meeting, cfg):
    """`cfg` is a HandoverFollowupConfig row. Recipients = team + organizer."""
    to = list(cfg.team_email_list())
    if meeting.organizer and meeting.organizer.email:
        to.append(meeting.organizer.email)
    to = list(dict.fromkeys(e for e in to if e))
    if not to:
        return
    b_date = _fmt_d(meeting.booking_date or (meeting.start_at.date()
                    if meeting.start_at else None))
    days = ""
    try:
        days = (date.today() - (meeting.booking_date or meeting.start_at.date())).days
    except Exception:
        pass
    body = f"""
      <p>Hi team,</p>
      <p>The handover call for <strong>{_jira(meeting)}</strong>
         ({meeting.tool_key}) was completed on <strong>{b_date}</strong>
         {f'({days} days ago)' if days != '' else ''}.</p>
      <p style="padding:12px 16px;background:#eef4fb;border-left:3px solid #1565c0;
                border-radius:6px;font-size:15px">
         <strong>Kindly move the JIRA {_jira(meeting)} to GO live.</strong></p>
      {_detail_rows(meeting)}
      <p style="margin-top:16px;color:#5a6b7b;font-size:13px">
         Once done, mark it GO-live on the EDCS-Gate dashboard so these
         reminders stop.</p>
    """
    html = _email_wrapper(
        title="Action needed — move JIRA to GO live",
        accent_colour="#1565c0",
        body_html=body,
    )
    _safe_send(
        f"[EDCS-Gate] GO-live reminder — {_jira(meeting)} ({meeting.tool_key})",
        html, to,
    )


# ── 4. escalation (global managers, day 15) ──────────────────────────────────
def escalation_notice(meeting, policy, cfg=None):
    """`policy` is the global EscalationPolicy; `cfg` optional per-tool config for CC."""
    to = list(policy.manager_email_list())
    cc = []
    if policy.cc_team:
        if cfg:
            cc += cfg.team_email_list()
        if meeting.organizer and meeting.organizer.email:
            cc.append(meeting.organizer.email)
    recipients = list(dict.fromkeys(e for e in (to + cc) if e))
    if not recipients:
        return
    b_date = _fmt_d(meeting.booking_date or (meeting.start_at.date()
                    if meeting.start_at else None))
    days = ""
    try:
        days = (date.today() - (meeting.booking_date or meeting.start_at.date())).days
    except Exception:
        pass
    body = f"""
      <p>Hello,</p>
      <p>This is an <strong>escalation</strong>: the handover for
         <strong>{_jira(meeting)}</strong> ({meeting.tool_key}) was completed on
         <strong>{b_date}</strong>{f' — {days} days ago' if days != '' else ''},
         and the JIRA has <strong>not yet been marked GO-live</strong>.</p>
      <p style="padding:12px 16px;background:#fff4f4;border-left:3px solid #c62828;
                border-radius:6px;font-size:15px">
         Please follow up with the team to move
         <strong>{_jira(meeting)}</strong> to GO live.</p>
      {_detail_rows(meeting)}
    """
    html = _email_wrapper(
        title="Escalation — handover not yet GO-live",
        accent_colour="#c62828",
        body_html=body,
    )
    _safe_send(
        f"[EDCS-Gate] ESCALATION — {_jira(meeting)} not GO-live "
        f"({meeting.tool_key})",
        html, recipients,
    )
