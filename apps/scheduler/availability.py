"""Tool-exclusive availability (Handover model).

A date is blocked for a tool if it's in the past, a weekend, a holiday /
blocked date, or every DailySlot that day is already booked for that tool
(by ANYONE — first come, first served). Live calendar (Graph) is not
consulted in powerautomate_email mode."""
from datetime import date as date_cls, timedelta

from apps.adminconfig.models import Holiday, BlockedDate
from .models import DailySlot, Meeting

ACTIVE = ["PENDING", "REQUESTED", "CONFIRMED"]
MAX_ADVANCE_DAYS = 60


def active_slots():
    return list(DailySlot.objects.filter(is_active=True))


def booked_slot_ids(tool_key: str, d: date_cls) -> set:
    return set(Meeting.objects.filter(
        tool_key=tool_key, booking_date=d, status__in=ACTIVE)
        .values_list("slot_id", flat=True))


def date_status(tool_key: str, d: date_cls, today=None) -> str:
    """'blocked' | 'booked' | 'bookable' for the calendar grid."""
    today = today or date_cls.today()
    if d < today or d > today + timedelta(days=MAX_ADVANCE_DAYS):
        return "blocked"
    if d.weekday() >= 5:
        return "blocked"
    if Holiday.objects.filter(date=d).exists() or \
       BlockedDate.objects.filter(date=d).exists():
        return "blocked"
    slots = active_slots()
    if not slots:
        return "blocked"
    if booked_slot_ids(tool_key, d) >= {s.id for s in slots}:
        return "booked"
    return "bookable"


def month_map(tool_key: str, year: int, month: int) -> dict:
    """{iso_date: status} for every day of the month."""
    from calendar import monthrange
    days = monthrange(year, month)[1]
    return {date_cls(year, month, i).isoformat():
            date_status(tool_key, date_cls(year, month, i))
            for i in range(1, days + 1)}


def free_slots(tool_key: str, d: date_cls) -> list:
    if date_status(tool_key, d) != "bookable" and date_status(tool_key, d) != "booked":
        # blocked date → nothing bookable
        if date_status(tool_key, d) == "blocked":
            return []
    booked = booked_slot_ids(tool_key, d)
    return [{"slot_id": s.id, "label": s.label,
             "start": s.start_time.strftime("%H:%M"),
             "end": s.end_time.strftime("%H:%M")}
            for s in active_slots() if s.id not in booked]
