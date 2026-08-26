"""Booking queries, stats, filters, and Excel export for the dashboard."""
import io
from datetime import date

from django.db.models import Q

from .models import Meeting

ACTIVE = ["PENDING", "REQUESTED", "CONFIRMED"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _display_status(m: Meeting, today=None) -> str:
    today = today or date.today()
    if m.status == "CANCELLED":
        return "cancelled"
    if m.status == "FAILED":
        return "failed"
    d = m.booking_date or m.start_at.date()
    return "completed" if d < today else "scheduled"

# ---------------------------------------------------------------------------
# Querysets
# ---------------------------------------------------------------------------

def all_bookings():
    return (
        Meeting.objects
        .select_related("organizer", "slot", "validation_run",
                        "validation_run__automation_type")   # ← new join
        .prefetch_related("attendees")
        .order_by("-start_at")
    )

def filtered_bookings(q="", tool="", status="", date_from="", date_to=""):
    rows = all_bookings()
    if q:
        rows = rows.filter(
            Q(organizer__username__icontains=q) | Q(tool_key__icontains=q) |
            Q(subject__icontains=q) | Q(validation_run__jira_id__icontains=q) |
            Q(attendees__email__icontains=q)
        ).distinct()
    if tool:
        rows = rows.filter(tool_key=tool)
    if date_from:
        rows = rows.filter(booking_date__gte=date_from)
    if date_to:
        rows = rows.filter(booking_date__lte=date_to)

    out = []
    for m in rows:
        disp = _display_status(m)
        if status and disp != status:
            continue

        vr = m.validation_run
        # Automation Type display name (e.g. "Execution") — new field
        at = vr.automation_type if vr else None

        out.append({
            "m": m,
            "display_status": disp,
            "jira_id": vr.jira_id if vr else "",
            "customer_name": vr.customer_name if vr else "",
            "automation_name": vr.automation_name if vr else "",
            # ↓ NEW fields
            "automation_type_display": at.display_name if at else "—",
            "automation_type_key": at.key if at else "",
            "requires_scheduling": at.requires_scheduling if at else True,
        })
    return out

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def booking_stats():
    today = date.today()
    rows = list(Meeting.objects.all())
    return {
        "total":     len(rows),
        "upcoming":  sum(1 for m in rows if m.status in ACTIVE
                         and (m.booking_date or m.start_at.date()) >= today),
        "completed": sum(1 for m in rows if m.status in ACTIVE
                         and (m.booking_date or m.start_at.date()) < today),
        "cancelled": sum(1 for m in rows if m.status == "CANCELLED"),
    }

def no_meeting_stats():
    """Count of doc-only (Healthcheck / Backup) PASSED runs — for dashboard stat card."""
    from apps.validation.models import ValidationRun
    return ValidationRun.objects.filter(
        automation_type__requires_scheduling=False,
        status="PASSED",
    ).count()

# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

# Colour palette (openpyxl ARGB — no leading #)
_CLR = {
    "header_fill":   "FF1C3C5A",   # dark navy  (header background)
    "header_font":   "FFFFFFFF",   # white      (header text)
    "subheader":     "FFD9E8F5",   # light blue (sheet-2 section header)
    "row_even":      "FFF5F9FF",   # very light blue
    "row_odd":       "FFFFFFFF",   # white
    "type_exec":     "FFD6EAD7",   # soft green  — Execution
    "type_hc":       "FFFFF3CD",   # soft yellow — Healthcheck
    "type_backup":   "FFE2D9F3",   # soft purple — Backup
    "type_other":    "FFEDEDED",   # light grey  — anything else
    "pass_green":    "FFD6EAD7",
    "fail_red":      "FFFFD7D7",
}

_TYPE_COLOURS = {
    "EXECUTION":   _CLR["type_exec"],
    "HEALTHCHECK": _CLR["type_hc"],
    "BACKUP":      _CLR["type_backup"],
}

def _type_colour(key: str) -> str:
    return _TYPE_COLOURS.get((key or "").upper(), _CLR["type_other"])

def _status_colour(status: str) -> str:
    s = (status or "").lower()
    if s in ("scheduled", "completed"):
        return _CLR["pass_green"]
    if s in ("cancelled", "failed"):
        return _CLR["fail_red"]
    return _CLR["type_other"]

def bookings_workbook(rows) -> io.BytesIO:
    """
    Build a styled two-sheet Excel workbook.

    Sheet 1 — "Handover Bookings"  : all meetings (Execution type)
    Sheet 2 — "No Meeting Needed"  : Healthcheck / Backup PASSED runs
    """
    from openpyxl import Workbook
    from openpyxl.styles import (Font, PatternFill, Alignment,
                                  Border, Side, GradientFill)
    from openpyxl.utils import get_column_letter
    from apps.validation.models import ValidationRun

    wb = Workbook()

    # ------------------------------------------------------------------ #
    # Shared style helpers
    # ------------------------------------------------------------------ #
    def _fill(hex_argb):
        return PatternFill("solid", fgColor=hex_argb)

    def _border():
        s = Side(style="thin", color="FFD0D0D0")
        return Border(left=s, right=s, top=s, bottom=s)

    def _header_font():
        return Font(bold=True, color=_CLR["header_font"], size=10)

    def _data_font(bold=False):
        return Font(bold=bold, size=10)

    def _center():
        return Alignment(horizontal="center", vertical="center", wrap_text=True)

    def _left():
        return Alignment(horizontal="left", vertical="center", wrap_text=True)

    def _style_header_row(ws, row_idx=1):
        for cell in ws[row_idx]:
            cell.fill      = _fill(_CLR["header_fill"])
            cell.font      = _header_font()
            cell.alignment = _center()
            cell.border    = _border()

    def _auto_width(ws, min_w=12, max_w=42):
        for col in ws.columns:
            letter = get_column_letter(col[0].column)
            width  = max(min_w, min(max_w,
                         max(len(str(c.value or "")) for c in col) + 3))
            ws.column_dimensions[letter].width = width

    # ================================================================== #
    # SHEET 1 — Handover Bookings
    # ================================================================== #
    ws1 = wb.active
    ws1.title = "Handover Bookings"
    ws1.freeze_panes = "A2"
    ws1.row_dimensions[1].height = 22

    HEADERS_S1 = [
        "Username", "Tool", "Automation Type", "Customer",
        "Date", "Slot", "JIRA ID", "Automation Name",
        "Developers", "Scrum Masters", "CC",
        "Status", "Created",
    ]
    ws1.append(HEADERS_S1)
    _style_header_row(ws1)

    for idx, r in enumerate(rows, start=2):
        m        = r["m"]
        att      = list(m.attendees.all())
        pick     = lambda k: ", ".join(a.email for a in att if a.type == k)
        at_key   = r.get("automation_type_key", "")
        at_disp  = r.get("automation_type_display", "—")
        disp_st  = r["display_status"]

        ws1.append([
            m.organizer.username,
            m.tool_key,
            at_disp,                                                     # ← NEW
            m.validation_run.customer_name if m.validation_run else "",
            str(m.booking_date or m.start_at.date()),
            m.slot.label if m.slot else "",
            r["jira_id"],
            r["automation_name"],
            pick("DEVELOPER"),
            pick("SCRUM_MASTER"),
            pick("CC"),
            disp_st,
            m.created_at.strftime("%Y-%m-%d %H:%M"),
        ])

        row_fill = _fill(_CLR["row_even"] if idx % 2 == 0 else _CLR["row_odd"])
        for col_idx, cell in enumerate(ws1[idx], start=1):
            cell.border    = _border()
            cell.alignment = _center() if col_idx in (1, 2, 3, 5, 6, 12, 13) else _left()
            cell.font      = _data_font()
            # Automation Type column (col 3) — colour by type
            if col_idx == 3:
                cell.fill = _fill(_type_colour(at_key))
            # Status column (col 12) — colour by status
            elif col_idx == 12:
                cell.fill = _fill(_status_colour(disp_st))
            else:
                cell.fill = row_fill

    _auto_width(ws1)

    # ================================================================== #
    # SHEET 2 — No Meeting Needed  (Healthcheck / Backup PASSED runs)
    # ================================================================== #
    ws2 = wb.create_sheet("No Meeting Needed")
    ws2.freeze_panes = "A2"
    ws2.row_dimensions[1].height = 22

    HEADERS_S2 = [
        "Username", "Tool", "Automation Type", "Customer",
        "JIRA ID", "Automation Name",
        "Status", "Remarks", "Scan Date",
    ]
    ws2.append(HEADERS_S2)
    _style_header_row(ws2)

    # Fetch doc-only PASSED runs
    no_meeting_runs = (
        ValidationRun.objects
        .filter(automation_type__requires_scheduling=False)
        .select_related("requested_by", "tool", "automation_type")
        .order_by("-started_at")
    )

    STATUS_REMARKS = {
        "PASSED": "No meeting needed — verification passed",
        "FAILED": "Verification failed — no meeting required",
        "CANCELLED": "Scan cancelled",
        "RUNNING": "Scan in progress",
        "PENDING": "Scan pending",
        "ERROR": "Scan error",
    }

    for idx, vr in enumerate(no_meeting_runs, start=2):
        at      = vr.automation_type
        at_key  = at.key if at else ""
        at_disp = at.display_name if at else "—"
        remark  = STATUS_REMARKS.get(vr.status, vr.status)

        ws2.append([
            vr.requested_by.username if vr.requested_by else "",
            vr.tool.key if vr.tool else "",
            at_disp,
            getattr(vr, "customer_name", ""),
            vr.jira_id,
            getattr(vr, "automation_name", ""),
            vr.status,
            remark,
            vr.started_at.strftime("%Y-%m-%d %H:%M") if vr.started_at else "",
        ])

        row_fill = _fill(_CLR["row_even"] if idx % 2 == 0 else _CLR["row_odd"])
        for col_idx, cell in enumerate(ws2[idx], start=1):
            cell.border    = _border()
            cell.font      = _data_font()
            cell.alignment = _center() if col_idx in (1, 2, 3, 7, 9) else _left()
            # Automation Type col (3)
            if col_idx == 3:
                cell.fill = _fill(_type_colour(at_key))
            # Status col (7)
            elif col_idx == 7:
                cell.fill = _fill(
                    _CLR["pass_green"] if vr.status == "PASSED" else _CLR["fail_red"]
                )
            else:
                cell.fill = row_fill

    _auto_width(ws2)

    # ------------------------------------------------------------------ #
    buf = io.BytesIO()
    wb.save(buf)
    return buf

