import json
import re
from datetime import datetime, date
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.adminconfig.models import Holiday, MeetingTemplate, ToolConfig
from apps.audit.log import log_action
from apps.rbac.decorators import require_permission
from apps.rbac.permissions import user_daily_limit
from apps.validation.models import ValidationRun
from .availability import month_map, free_slots, date_status
from .models import Meeting, MeetingAttendee, DailySlot
from .tasks import schedule_reminders_for

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _parse_email_list(raw, required):
    emails = [e.strip().lower() for e in (raw or "").split(",") if e.strip()]
    if required and not emails:
        return None, "at least one email is required."
    for e in emails:
        if not EMAIL_RE.fullmatch(e):
            return None, f"'{e}' is not a valid email address."
    return emails, ""


def _build_meeting_subject_body(tool_key, run, ref):
    """Resolve the meeting subject/body from the tool's template (or the
    built-in default), stamping in the correlation `ref`."""
    tmpl = (MeetingTemplate.objects.filter(tool__key=tool_key).first()
            or MeetingTemplate.objects.filter(tool__isnull=True).first())
    fmt_kwargs = dict(
        jira_id=run.jira_id if run else "",
        automation_name=run.automation_name if run else "",
        tool_name=(run.tool.display_name if run else tool_key),
        ref=ref)
    subject = (tmpl.subject_pattern if tmpl else
               "Handover Call — {tool_name} | {jira_id} — {automation_name} [{ref}]"
               ).format(**fmt_kwargs)
    body = (tmpl.body_html if tmpl else "").format(**fmt_kwargs)
    compulsory = [e.strip().lower() for e in (tmpl.default_attendees if tmpl else [])
                  if e.strip()]
    return subject, body, compulsory


@require_permission("schedules.view")
def scheduler_page(request):
    run = None
    run_id = request.GET.get("run_id")
    if run_id:
        run = get_object_or_404(ValidationRun, pk=run_id)
        if run.status != "PASSED":
            return redirect(f"/validations/{run.id}/report/")
    else:
        # Handover behaviour: latest passed run of this user, else redirect
        run = (ValidationRun.objects.filter(requested_by=request.user,
                                            status="PASSED")
               .order_by("-finished_at").first())
        if not run:
            messages.warning(request,
                "Please complete a successful verification before scheduling.")
            return redirect("/verify/")

    holidays = Holiday.objects.filter(date__gte=date.today()).order_by("date")[:12]
    slots = DailySlot.objects.filter(is_active=True)
    return render(request, "scheduler.html", {
        "nav": "scheduler", "run": run, "tool": run.tool,
        "holidays": holidays, "slots": slots,
        "single_slot": slots[0] if len(slots) == 1 else None,
    })


@require_permission("schedules.view")
def month_json(request):
    tool = request.GET.get("tool", "")
    year, month = int(request.GET.get("year")), int(request.GET.get("month"))
    return JsonResponse({"days": month_map(tool, year, month)})


@require_permission("schedules.view")
def slots_json(request):
    tool = request.GET.get("tool", "")
    d = date.fromisoformat(request.GET.get("date"))
    return JsonResponse({"slots": free_slots(tool, d)})


@require_permission("schedules.create")
@require_POST
def book(request):
    data = json.loads(request.body or "{}")
    tz = ZoneInfo(settings.TIME_ZONE)

    run = get_object_or_404(ValidationRun, pk=data.get("run_id"))
    if run.status != "PASSED":
        return JsonResponse({"error": "Validation has not passed."}, status=400)
    tool_key = run.tool.key

    try:
        d = date.fromisoformat(data.get("date", ""))
    except ValueError:
        return JsonResponse({"error": "Please choose a valid date."}, status=400)
    slot = get_object_or_404(DailySlot, pk=data.get("slot_id"), is_active=True)

    devs, err = _parse_email_list(data.get("developer_email"), required=True)
    if err:
        return JsonResponse({"error": f"Developer email: {err}"}, status=400)
    sms, err = _parse_email_list(data.get("scrum_master_email"), required=True)
    if err:
        return JsonResponse({"error": f"Scrum Master email: {err}"}, status=400)
    ccs, err = _parse_email_list(data.get("cc_email"), required=False)
    if err:
        return JsonResponse({"error": f"CC email: {err}"}, status=400)

    # Exclusivity re-check (also enforced by the DB constraint)
    if date_status(tool_key, d) != "bookable" or \
       not any(s["slot_id"] == slot.id for s in free_slots(tool_key, d)):
        return JsonResponse(
            {"error": "That date/slot is no longer available for this tool."},
            status=409)

    # One active meeting per JIRA ID, globally across all tools — a JIRA
    # represents one handover, so a second booking while the first is
    # still PENDING/REQUESTED/CONFIRMED is almost always a mistake.
    if Meeting.objects.filter(
            validation_run__jira_id=run.jira_id,
            status__in=["PENDING", "REQUESTED", "CONFIRMED"]).exists():
        return JsonResponse(
            {"error": f"This JIRA ID already has a scheduled meeting. "
                      f"Please cancel the existing meeting before scheduling again."},
            status=409)

    # Per-day booking quota from the user's role(s).
    #   None -> unlimited, 0 -> not allowed, N -> at most N/day.
    from django.utils import timezone as _tz
    cap = user_daily_limit(request.user, "max_meetings_per_day")
    if cap is not None:
        booked_today = Meeting.objects.filter(
            organizer=request.user,
            created_at__date=_tz.localdate(),
            status__in=["PENDING", "REQUESTED", "CONFIRMED"]).count()
        if cap == 0:
            return JsonResponse(
                {"error": "Your role does not permit booking handover meetings."},
                status=403)
        if booked_today >= cap:
            return JsonResponse(
                {"error": f"Daily limit reached: your role allows {cap} handover "
                          f"meeting(s) per day. Please try again tomorrow or ask "
                          f"an administrator."},
                status=403)

    # A short, stable, unique id per meeting — the same one Power Automate
    # uses to find-and-cancel the right calendar event later (meeting_ref).
    # Generating the meeting's PK explicitly here (rather than letting
    # Meeting.objects.create() default it) lets us bake this id into the
    # subject/body BEFORE the row exists.
    import uuid as _uuid
    from . import pa_mail
    meeting_id = _uuid.uuid4()
    ref = str(meeting_id).replace("-", "")[:12]

    subject, body, compulsory = _build_meeting_subject_body(tool_key, run, ref)
    organizer_email = (request.user.email or "").lower()

    start = datetime.combine(d, slot.start_time, tzinfo=tz)
    end = datetime.combine(d, slot.end_time, tzinfo=tz)
    meeting = Meeting.objects.create(
        id=meeting_id, validation_run=run, organizer=request.user, tool_key=tool_key,
        booking_date=d, slot=slot, subject=subject, body_html=body,
        start_at=start, end_at=end, timezone=settings.TIME_ZONE)

    seen = set()
    def add(emails, kind):
        for e in emails:
            if e not in seen:
                seen.add(e)
                MeetingAttendee.objects.create(meeting=meeting, email=e, type=kind)
    add(devs, "DEVELOPER")
    add(sms, "SCRUM_MASTER")
    add(compulsory, "REQUIRED")
    if organizer_email:
        add([organizer_email], "REQUIRED")
    add(ccs, "CC")

    try:
        pa_mail.send_meeting_request(meeting)
        meeting.status = Meeting.Status.REQUESTED
        meeting.save()
        schedule_reminders_for(meeting)
    except pa_mail.PAConfigError as e:
        meeting.status = Meeting.Status.FAILED
        meeting.save()
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        meeting.status = Meeting.Status.FAILED
        meeting.save()
        return JsonResponse(
            {"error": f"Could not send the meeting request email: {e}"}, status=502)
    log_action(request.user, "meeting.created", "schedules",
              f"{tool_key} / {run.jira_id} on {d} ({slot.label})")
    return JsonResponse({"meeting_id": str(meeting.id)}, status=201)


@login_required
def confirmation(request, meeting_id):
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    return render(request, "confirm.html", {"nav": "scheduler", "meeting": meeting})


@require_permission("schedules.cancel")
@require_POST
def cancel_booking(request, meeting_id):
    """Dashboard cancel: requires a reason (mandatory, per audit policy),
    sends the [EDCS-CANCEL] Power Automate trigger so the real Teams/Outlook
    meeting is cancelled, then soft-cancels locally (which frees the
    tool/date/slot) and records who cancelled it, when, and why."""
    m = get_object_or_404(Meeting, pk=meeting_id)
    if m.status == Meeting.Status.CANCELLED:
        messages.info(request, "That booking is already cancelled.")
        return redirect("/")

    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "A cancellation reason is required.")
        return redirect("/")
    if len(reason) > 1000:
        reason = reason[:1000]

    pa_sent = False
    if m.status == Meeting.Status.REQUESTED:   # a real meeting request went out
        from . import pa_mail
        try:
            pa_mail.send_meeting_cancel(m)
            pa_sent = True
        except Exception as e:
            messages.warning(request,
                f"Booking cancelled in the tool, but the Teams-cancellation "
                f"email could not be sent ({e}). Cancel the Outlook invite "
                f"manually or retry later.")

    from django.utils import timezone
    m.status = Meeting.Status.CANCELLED
    m.cancelled_by = request.user
    m.cancelled_at = timezone.now()
    m.cancellation_reason = reason
    m.save()
    m.reminders.update(status="CANCELLED")

    log_action(request.user, "meeting.cancelled", "schedules",
              f"Meeting {m.id} ({m.subject}) cancelled. Reason: {reason}")

    if pa_sent:
        messages.info(request,
            "Booking cancelled. The Teams meeting cancellation has been sent "
            "to the scheduling automation — attendees will receive the "
            "cancellation from Outlook shortly.")
    elif m.validation_run is None or not pa_sent:
        messages.info(request, "Booking cancelled.")
    return redirect("/")


@require_permission("schedules.edit")
@require_POST
def reschedule_booking(request, meeting_id):
    """Move an existing booking to a new date/slot by REUSING the two
    existing Power Automate flows — no new flow is required:

        1. Send the [EDCS-CANCEL] trigger for the OLD slot (cancels the
           existing Teams/Outlook event via its [EDCSREF-<ref>] marker).
        2. Send a fresh [EDCS-GATE-MEETING] create trigger for the NEW slot
           (a brand-new meeting row with a new ref -> new Teams event).

    Implemented as cancel-old + create-new so the old and new events each
    carry their own correlation ref, exactly like a manual cancel followed
    by a manual booking. Attendees are copied across automatically.
    A reschedule is NOT counted against the daily booking quota (it moves an
    existing handover rather than creating new demand)."""
    old = get_object_or_404(Meeting, pk=meeting_id)
    if old.status not in (Meeting.Status.REQUESTED, Meeting.Status.PENDING,
                          Meeting.Status.CONFIRMED):
        messages.error(request, "Only an active booking can be rescheduled.")
        return redirect("/")

    run = old.validation_run
    tool_key = old.tool_key
    tz = ZoneInfo(settings.TIME_ZONE)

    # ---- validate the requested new date/slot -----------------------------
    try:
        d = date.fromisoformat((request.POST.get("date") or "").strip())
    except ValueError:
        messages.error(request, "Please choose a valid new date.")
        return redirect("/")
    slot = get_object_or_404(DailySlot, pk=request.POST.get("slot_id"), is_active=True)
    reason = (request.POST.get("reason") or "").strip()[:1000]

    if date_status(tool_key, d) != "bookable" or \
       not any(s["slot_id"] == slot.id for s in free_slots(tool_key, d)):
        messages.error(request,
            "That date/slot is no longer available for this tool. "
            "Please pick another slot.")
        return redirect("/")

    from . import pa_mail
    from django.utils import timezone as _tz

    # Reschedule = create-the-NEW-meeting-first, then cancel the OLD one.
    # This ordering guarantees a failed email send can NEVER leave the user
    # with the old slot cancelled and nothing booked:
    #   1) create the NEW meeting row + send its [EDCS-GATE-MEETING] trigger.
    #      If that send fails, delete the new row and KEEP the old booking
    #      exactly as it was.
    #   2) only once the new request is safely sent do we fire [EDCS-CANCEL]
    #      for the OLD meeting and soft-cancel it locally.
    # (The new date/slot always differs from the old, so the two bookings
    #  never collide on the unique tool/date/slot constraint.)

    # ---- 1) Create + send the NEW meeting (new slot) ---------------------
    import uuid as _uuid
    meeting_id_new = _uuid.uuid4()
    ref = str(meeting_id_new).replace("-", "")[:12]
    subject, body, _ = _build_meeting_subject_body(tool_key, run, ref)

    start = datetime.combine(d, slot.start_time, tzinfo=tz)
    end = datetime.combine(d, slot.end_time, tzinfo=tz)
    new = Meeting.objects.create(
        id=meeting_id_new, validation_run=run, organizer=old.organizer,
        tool_key=tool_key, booking_date=d, slot=slot, subject=subject,
        body_html=body, start_at=start, end_at=end, timezone=settings.TIME_ZONE)

    # Copy the old meeting's attendee list onto the new booking.
    for a in old.attendees.all():
        MeetingAttendee.objects.create(meeting=new, email=a.email, type=a.type)

    try:
        pa_mail.send_meeting_request(new)
        new.status = Meeting.Status.REQUESTED
        new.save()
        schedule_reminders_for(new)
    except Exception as e:
        # New request failed — roll the new row back and leave the existing
        # booking fully intact so the user hasn't lost anything.
        new.delete()
        messages.error(request,
            f"Could not send the new meeting request ({e}). Your existing "
            f"booking has been left unchanged — please try rescheduling again.")
        return redirect("/")

    # ---- 2) New booking is live — now cancel the OLD meeting (old slot) --
    if old.status == Meeting.Status.REQUESTED:
        try:
            pa_mail.send_meeting_cancel(old)
        except Exception as e:
            messages.warning(request,
                f"New meeting booked, but the cancellation of the old slot "
                f"could not be sent ({e}). Cancel the old Outlook invite "
                f"manually if it remains.")
    resched_note = f"Rescheduled to {d} ({slot.label})"
    old.status = Meeting.Status.CANCELLED
    old.cancelled_by = request.user
    old.cancelled_at = _tz.now()
    old.cancellation_reason = (f"{resched_note}. {reason}" if reason else resched_note)
    old.save()
    old.reminders.update(status="CANCELLED")

    log_action(request.user, "meeting.cancelled", "schedules",
               f"Meeting {old.id} rescheduled away from {old.booking_date} "
               f"to {d} ({slot.label})")
    log_action(request.user, "meeting.created", "schedules",
               f"{tool_key} / {run.jira_id if run else ''} rescheduled to "
               f"{d} ({slot.label})")
    messages.success(request,
        f"Handover call rescheduled to {d} ({slot.label}). A new Teams meeting "
        f"request has been sent and the old slot has been cancelled.")
    return redirect("/")
