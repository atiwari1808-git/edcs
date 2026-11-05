"""
DROP-IN REPLACEMENT for bookings_workbook() in apps/scheduler/services.py
=========================================================================

WHAT CHANGED (nothing else in services.py needs to change):
  • Sheet 1 "Handover Bookings" now carries the two explicit dates the
    dashboard shows:
        - "Handover Initiated"  = Meeting.created_at   (date the doc was
                                   verified & the call was booked)  [date+time]
        - "Handover Date"       = Meeting.start_at      (the scheduled
                                   meeting date AND time)            [date+time]
    …and the previously-missing audit columns:
        - "Cancelled / Rescheduled By"
        - "Reason"  (cancellation reason, or the "Rescheduled to …" note)
  • Sheet 2 "No Meeting Needed" labels the verification timestamp as
    "Handover Initiated" and mirrors it into "Handover Date" (doc-only runs
    have no scheduled meeting, so both dates are the verification time).
  • Filtering is UNCHANGED and already correct: dashboard_export() calls
    filtered_bookings() with the same q/tool/status/jira_type/date_from/
    date_to (+ scrum-master scope) as the page, so the download always
    contains exactly the rows matching the filters currently applied.

HOW TO APPLY:
  Replace the whole `def bookings_workbook(rows) -> io.BytesIO:` function in
  apps/scheduler/services.py with the one below (keep the imports/_CLR block
  and the _type_colour/_status_colour helpers that are already in that file).
"""
from __future__ import annotations
import io


def bookings_workbook(rows) -> io.BytesIO:
    """Build a styled two-sheet Excel workbook with ALL handover details."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from apps.validation.models import ValidationRun

    wb = Workbook()

    def _fill(hex_argb):   return PatternFill("solid", fgColor=hex_argb)
    def _border():
        s = Side(style="thin", color="FFD0D0D0")
        return Border(left=s, right=s, top=s, bottom=s)
    def _header_font():    return Font(bold=True, color=_CLR["header_font"], size=10)
    def _data_font(bold=False): return Font(bold=bold, size=10)
    def _center():         return Alignment(horizontal="center", vertical="center", wrap_text=True)
    def _left():           return Alignment(horizontal="left",  vertical="center", wrap_text=True)

    def _style_header_row(ws, row_idx=1):
        for cell in ws[row_idx]:
            cell.fill = _fill(_CLR["header_fill"]); cell.font = _header_font()
            cell.alignment = _center(); cell.border = _border()

    def _auto_width(ws, min_w=12, max_w=48):
        for col in ws.columns:
            letter = get_column_letter(col[0].column)
            width = max(min_w, min(max_w, max(len(str(c.value or "")) for c in col) + 3))
            ws.column_dimensions[letter].width = width

    def _dt(v):  return v.strftime("%Y-%m-%d %H:%M") if v else ""

    # ================= SHEET 1 — Handover Bookings ================= #
    ws1 = wb.active
    ws1.title = "Handover Bookings"
    ws1.freeze_panes = "A2"
    ws1.row_dimensions[1].height = 22
    HEADERS_S1 = [
        "Organizer", "Tool", "Automation Type", "JIRA Type", "Customer",
        "JIRA ID", "Parent JIRA", "Enhancement JIRA", "Automation Name",
        "Scrum Masters", "Developers", "CC",
        "Handover Initiated", "Handover Date", "Slot",
        "Status", "Cancelled / Rescheduled By", "Reason",
    ]
    ws1.append(HEADERS_S1)
    _style_header_row(ws1)
    AT_COL_1, STATUS_COL_1 = 3, 16
    CENTER_1 = {2, 3, 4, 6, 7, 8, 13, 14, 15, 16}

    for idx, r in enumerate(rows, start=2):
        m    = r["m"]
        att  = list(m.attendees.all())
        pick = lambda k: ", ".join(a.email for a in att if a.type == k)
        sm_names = ", ".join(s["name"] for s in r.get("scrum_masters", [])) or pick("SCRUM_MASTER")
        at_key  = r.get("automation_type_key", "")
        at_disp = r.get("automation_type_display", "")
        disp_st = r["display_status"]
        cancelled_by = m.cancelled_by.username if m.cancelled_by else ""
        ws1.append([
            m.organizer.username,
            m.tool_key,
            at_disp,
            r.get("jira_type_display", ""),
            m.validation_run.customer_name if m.validation_run else "",
            r["jira_id"],
            r.get("parent_jira_id", ""),
            r.get("enhancement_jira_id", ""),
            r["automation_name"],
            sm_names,
            pick("DEVELOPER"),
            pick("CC"),
            _dt(m.created_at),                       # Handover Initiated
            _dt(m.start_at),                         # Handover Date (date+time)
            m.slot.label if m.slot else "",
            disp_st,
            cancelled_by,
            m.cancellation_reason or "",
        ])
        row_fill = _fill(_CLR["row_even"] if idx % 2 == 0 else _CLR["row_odd"])
        for col_idx, cell in enumerate(ws1[idx], start=1):
            cell.border = _border()
            cell.alignment = _center() if col_idx in CENTER_1 else _left()
            cell.font = _data_font()
            if col_idx == AT_COL_1:      cell.fill = _fill(_type_colour(at_key))
            elif col_idx == STATUS_COL_1: cell.fill = _fill(_status_colour(disp_st))
            else:                         cell.fill = row_fill
    _auto_width(ws1)

    # ================= SHEET 2 — No Meeting Needed ================= #
    ws2 = wb.create_sheet("No Meeting Needed")
    ws2.freeze_panes = "A2"
    ws2.row_dimensions[1].height = 22
    HEADERS_S2 = [
        "Organizer", "Tool", "Automation Type", "JIRA Type", "Customer",
        "JIRA ID", "Parent JIRA", "Enhancement JIRA", "Automation Name",
        "Status", "Remarks", "Handover Initiated", "Handover Date",
    ]
    ws2.append(HEADERS_S2)
    _style_header_row(ws2)
    AT_COL_2, STATUS_COL_2 = 3, 10
    CENTER_2 = {2, 3, 4, 6, 7, 8, 10, 12, 13}

    no_meeting_runs = (
        ValidationRun.objects
        .filter(automation_type__requires_scheduling=False)
        .select_related("requested_by", "tool", "automation_type", "jira_type")
        .order_by("-started_at")
    )
    STATUS_REMARKS = {
        "PASSED": "No meeting needed - verification passed",
        "FAILED": "Verification failed - no meeting required",
        "CANCELLED": "Scan cancelled", "RUNNING": "Scan in progress",
        "PENDING": "Scan pending", "ERROR": "Scan error",
    }
    for idx, vr in enumerate(no_meeting_runs, start=2):
        at = vr.automation_type
        at_key = at.key if at else ""; at_disp = at.display_name if at else ""
        jt = vr.jira_type
        ws2.append([
            vr.requested_by.username if vr.requested_by else "",
            vr.tool.key if vr.tool else "",
            at_disp,
            jt.display_name if jt else "",
            getattr(vr, "customer_name", ""),
            vr.jira_id,
            getattr(vr, "parent_jira_id", ""),
            getattr(vr, "enhancement_jira_id", ""),
            getattr(vr, "automation_name", ""),
            vr.status,
            STATUS_REMARKS.get(vr.status, vr.status),
            _dt(vr.started_at),                      # Handover Initiated
            _dt(vr.started_at),                      # Handover Date (mirrors initiated - no meeting)
        ])
        row_fill = _fill(_CLR["row_even"] if idx % 2 == 0 else _CLR["row_odd"])
        for col_idx, cell in enumerate(ws2[idx], start=1):
            cell.border = _border(); cell.font = _data_font()
            cell.alignment = _center() if col_idx in CENTER_2 else _left()
            if col_idx == AT_COL_2:       cell.fill = _fill(_type_colour(at_key))
            elif col_idx == STATUS_COL_2: cell.fill = _fill(_CLR["pass_green"] if vr.status == "PASSED" else _CLR["fail_red"])
            else:                         cell.fill = row_fill
    _auto_width(ws2)

    buf = io.BytesIO()
    wb.save(buf)
    return buf
