"""Booking queries, stats, filters, and Excel export for the dashboard."""
import io
from datetime import date

from django.db.models import Q
from .models import Meeting

ACTIVE = ["PENDING", "REQUESTED", "CONFIRMED"]


def _display_status(m: Meeting, today=None) -> str:
    today = today or date.today()
    if m.status == "CANCELLED":
        return "cancelled"
    if m.status == "FAILED":
        return "failed"
    d = m.booking_date or m.start_at.date()
    return "completed" if d < today else "scheduled"


def all_bookings():
    return (Meeting.objects.select_related("organizer", "slot", "validation_run")
            .prefetch_related("attendees").order_by("-start_at"))


def filtered_bookings(q="", tool="", status="", date_from="", date_to=""):
    rows = all_bookings()
    if q:
        rows = rows.filter(
            Q(organizer__username__icontains=q) | Q(tool_key__icontains=q) |
            Q(subject__icontains=q) | Q(validation_run__jira_id__icontains=q) |
            Q(attendees__email__icontains=q)).distinct()
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
        out.append({"m": m, "display_status": disp,
                    "jira_id": m.validation_run.jira_id if m.validation_run else "",
                    "customer_name": m.validation_run.customer_name if m.validation_run else "",
                    "automation_name": m.validation_run.automation_name if m.validation_run else ""})
    return out


def booking_stats():
    today = date.today()
    rows = list(Meeting.objects.all())
    return {
        "total": len(rows),
        "upcoming": sum(1 for m in rows if m.status in ACTIVE
                        and (m.booking_date or m.start_at.date()) >= today),
        "completed": sum(1 for m in rows if m.status in ACTIVE
                         and (m.booking_date or m.start_at.date()) < today),
        "cancelled": sum(1 for m in rows if m.status == "CANCELLED"),
    }


def bookings_workbook(rows) -> io.BytesIO:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Handover Bookings"
    ws.append(["Username", "Tool", "Customer", "Date", "Slot", "JIRA ID", "Automation Name",
               "Developers", "Scrum Masters", "CC", "Status", "Created"])
    for r in rows:
        m = r["m"]
        att = list(m.attendees.all())
        pick = lambda k: ", ".join(a.email for a in att if a.type == k)
        ws.append([
            m.organizer.username, m.tool_key,
            (m.validation_run.customer_name if m.validation_run else ""),
            str(m.booking_date or m.start_at.date()),
            m.slot.label if m.slot else "",
            r["jira_id"], r["automation_name"], pick("DEVELOPER"), pick("SCRUM_MASTER"), pick("CC"),
            r["display_status"], m.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            12, min(40, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf
