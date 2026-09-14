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
                        "validation_run__automation_type")
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
        # Automation Type display name (e.g. "Execution")
        at = vr.automation_type if vr else None
        out.append({
            "m": m,
            "display_status": disp,
            "jira_id": vr.jira_id if vr else "",
            "customer_name": vr.customer_name if vr else "",
            "automation_name": vr.automation_name if vr else "",
            "automation_type_display": at.display_name if at else "—",
            "automation_type_key": at.key if at else "",
            "requires_scheduling": at.requires_scheduling if at else True,
            # ↓ NEW: audit dates surfaced on the dashboard
            #   doc_verified      = when the verification completed (finished_at)
            #   handover_initiated = when the meeting was booked  (created_at)
            "doc_verified": (vr.finished_at if vr else None),
            "handover_initiated": m.created_at,
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
    """Count of doc-only (Healthcheck / Backup) PASSED runs — dashboard stat card."""
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


def _fmt_dt(value, fmt="%Y-%m-%d %H:%M"):
    return value.strftime(fmt) if value else ""


def bookings_workbook(rows) -> io.BytesIO:
    """
    Build a single-sheet, styled Excel workbook that COMBINES both dashboard
    tables into one consistent column layout:

        • Handover Bookings          (meeting-required rows passed in `rows`)
        • No Meeting Needed          (doc-only Healthcheck / Backup runs)

    Every column from both tables is preserved. Columns that don't apply to a
    given record type are left blank so the sheet stays perfectly aligned.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from apps.validation.models import ValidationRun

    wb = Workbook()

    def _fill(hex_argb):
        return PatternFill("solid", fgColor=hex_argb)

    def _border():
        sd = Side(style="thin", color="FFD0D0D0")
        return Border(left=sd, right=sd, top=sd, bottom=sd)

    def _center():
        return Alignment(horizontal="center", vertical="center", wrap_text=True)

    def _left():
        return Alignment(horizontal="left", vertical="center", wrap_text=True)

    def _auto_width(ws, min_w=12, max_w=42):
        for col in ws.columns:
            letter = get_column_letter(col[0].column)
            width = max(min_w, min(max_w,
                        max(len(str(c.value or "")) for c in col) + 3))
            ws.column_dimensions[letter].width = width

    # ------------------------------------------------------------------ #
    # Single combined sheet
    # ------------------------------------------------------------------ #
    ws = wb.active
    ws.title = "Handover Records"
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22

    HEADERS = [
        "Record Type", "Username", "Tool", "Automation Type", "Customer",
        "JIRA ID", "Automation Name", "Handover Date", "Slot",
        "Developers", "Scrum Masters", "CC",
        "Status", "Remarks", "Cancelled By",
        "Handover Initiated", "Scan / Verified Date",
    ]
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.fill = _fill(_CLR["header_fill"])
        cell.font = Font(bold=True, color=_CLR["header_font"], size=10)
        cell.alignment = _center()
        cell.border = _border()

    # Column groups (1-based) for alignment / colouring
    CENTER_COLS = (1, 3, 4, 8, 9, 13, 16, 17)
    TYPE_COL = 4
    STATUS_COL = 13

    row_idx = 1  # header written

    # ---- Section A: Handover Bookings -------------------------------- #
    for r in rows:
        m = r["m"]
        att = list(m.attendees.all())
        pick = lambda k: ", ".join(a.email for a in att if a.type == k)
        at_key = r.get("automation_type_key", "")
        at_disp = r.get("automation_type_display", "—")
        disp_st = r["display_status"]
        vr = m.validation_run
        row_idx += 1
        ws.append([
            "Handover Booking",
            m.organizer.username,
            m.tool_key,
            at_disp,
            vr.customer_name if vr else "",
            r["jira_id"],
            r["automation_name"],
            str(m.booking_date or m.start_at.date()),
            m.slot.label if m.slot else "",
            pick("DEVELOPER"),
            pick("SCRUM_MASTER"),
            pick("CC"),
            disp_st,
            m.cancellation_reason or "",
            m.cancelled_by.username if m.cancelled_by else "",
            _fmt_dt(r.get("handover_initiated") or m.created_at),
            _fmt_dt(vr.finished_at if vr else None),
        ])
        row_fill = _fill(_CLR["row_even"] if row_idx % 2 == 0 else _CLR["row_odd"])
        for col_idx, cell in enumerate(ws[row_idx], start=1):
            cell.border = _border()
            cell.font = Font(size=10)
            cell.alignment = _center() if col_idx in CENTER_COLS else _left()
            if col_idx == TYPE_COL:
                cell.fill = _fill(_type_colour(at_key))
            elif col_idx == STATUS_COL:
                cell.fill = _fill(_status_colour(disp_st))
            else:
                cell.fill = row_fill

    # ---- Section B: No Meeting Needed (doc-only runs) ---------------- #
    STATUS_REMARKS = {
        "PASSED": "No meeting needed — verification passed",
        "FAILED": "Verification failed — no meeting required",
        "CANCELLED": "Scan cancelled",
        "RUNNING": "Scan in progress",
        "PENDING": "Scan pending",
        "ERROR": "Scan error",
    }
    no_meeting_runs = (
        ValidationRun.objects
        .filter(automation_type__requires_scheduling=False)
        .select_related("requested_by", "tool", "automation_type")
        .order_by("-started_at")
    )
    for vr in no_meeting_runs:
        at = vr.automation_type
        at_key = at.key if at else ""
        at_disp = at.display_name if at else "—"
        remark = STATUS_REMARKS.get(vr.status, vr.status)
        row_idx += 1
        ws.append([
            "No Meeting Needed",
            vr.requested_by.username if vr.requested_by else "",
            vr.tool.key if vr.tool else "",
            at_disp,
            getattr(vr, "customer_name", ""),
            vr.jira_id,
            getattr(vr, "automation_name", ""),
            "",                       # Handover Date — N/A
            "",                       # Slot — N/A
            "",                       # Developers — N/A
            "",                       # Scrum Masters — N/A
            "",                       # CC — N/A
            vr.status,
            remark,
            "",                       # Cancelled By — N/A
            _fmt_dt(vr.started_at),   # Handover Initiated (run started)
            _fmt_dt(vr.finished_at),  # Scan / Verified date
        ])
        row_fill = _fill(_CLR["row_even"] if row_idx % 2 == 0 else _CLR["row_odd"])
        for col_idx, cell in enumerate(ws[row_idx], start=1):
            cell.border = _border()
            cell.font = Font(size=10)
            cell.alignment = _center() if col_idx in CENTER_COLS else _left()
            if col_idx == TYPE_COL:
                cell.fill = _fill(_type_colour(at_key))
            elif col_idx == STATUS_COL:
                cell.fill = _fill(
                    _CLR["pass_green"] if vr.status == "PASSED" else _CLR["fail_red"]
                )
            else:
                cell.fill = row_fill

    _auto_width(ws)

    buf = io.BytesIO()
    wb.save(buf)
    return buf
