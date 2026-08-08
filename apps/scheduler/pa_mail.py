"""Power Automate trigger email.

Booking a slot in `powerautomate_email` mode sends ONE plain-text email to
the dedicated trigger mailbox (PA_TRIGGER_MAILBOX). A Power Automate flow
watches that mailbox, extracts the JSON between the <EDCS-JSON> markers,
and creates the actual Teams meeting. See POWERAUTOMATE-SETUP.md for the
exact flow build steps and the matching Parse-JSON schema.

Design rules (do not break these — the Flow depends on them):
  * Subject starts with settings.PA_SUBJECT_PREFIX (Flow filters on it).
  * Body is PLAIN TEXT (never HTML) so extraction is deterministic.
  * The payload is a single line of compact JSON between the markers.
  * Datetimes are ISO-8601 WITHOUT offset + an explicit IANA `timezone`
    field, because Outlook's "Create event" action takes naive local time
    plus a timezone parameter.
"""
import json

from django.conf import settings
from django.core.mail import send_mail

MARKER_OPEN = "###EDCS-JSON-START###"
MARKER_CLOSE = "###EDCS-JSON-END###"


class PAConfigError(Exception):
    pass


def meeting_ref(meeting) -> str:
    """Short, unique, human-copyable correlation id stamped into the meeting
    subject as `[EDCSREF-<ref>]`. Derived from the Meeting UUID (first 12 hex
    chars — collision odds are negligible at this scale). The cancel flow
    finds the calendar event with `contains(subject,'EDCSREF-<ref>')` —
    robust even if someone edits the rest of the subject or the meeting is
    moved.

    Deliberately uses only [A-Za-z0-9-] — NO '#' or other URL-reserved
    characters. '#' looks convenient but breaks Power Automate's Get-events
    OData filter: the connector builds $filter into a request URL without
    percent-encoding reserved characters, so '#' gets read as a URL fragment
    delimiter and everything after it is silently truncated, corrupting the
    filter string. Keep this marker alphanumeric-and-hyphen only."""
    return str(meeting.id).replace("-", "")[:12]


def build_payload(meeting):
    all_att = list(meeting.attendees.all())
    required = sorted({a.email.strip().lower() for a in all_att
                       if a.email.strip() and a.type != "CC"})
    cc = sorted({a.email.strip().lower() for a in all_att
                 if a.email.strip() and a.type == "CC"} - set(required))
    attendees = required + cc
    ref = meeting_ref(meeting)
    return {
        "version": 3,
        "meeting_id": str(meeting.id),
        "ref": ref,
        "jira_id": (meeting.validation_run.jira_id
                    if meeting.validation_run else ""),
        "automation_name": (meeting.validation_run.automation_name
                            if meeting.validation_run else ""),
        "subject": meeting.subject,
        # The flow should use THIS as the Teams meeting subject — it carries
        # the correlation marker the cancel flow searches for.
        "subject_with_ref": f"{meeting.subject} [EDCSREF-{ref}]",
        "body_html": meeting.body_html or "",
        "start": meeting.start_at.astimezone(
            __import__("zoneinfo").ZoneInfo(meeting.timezone)
        ).strftime("%Y-%m-%dT%H:%M:%S"),
        "end": meeting.end_at.astimezone(
            __import__("zoneinfo").ZoneInfo(meeting.timezone)
        ).strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": meeting.timezone,
        "organizer_email": meeting.organizer.email or "",
        "attendees": attendees,
        # Required attendees (developers + scrum masters + compulsory + organizer)
        "attendees_semicolon": ";".join(required),
        # Optional/CC attendees — map to the Outlook action's Optional field
        "cc_semicolon": ";".join(cc),
    }


def send_meeting_request(meeting):
    """Send the trigger mail. Raises PAConfigError if mailbox unset."""
    if not settings.PA_TRIGGER_MAILBOX:
        raise PAConfigError(
            "PA_TRIGGER_MAILBOX is not set in .env — the Power Automate "
            "trigger mailbox address is required in powerautomate_email mode.")
    payload = build_payload(meeting)
    subject = (f"{settings.PA_SUBJECT_PREFIX} {payload['jira_id'] or 'MEETING'} "
               f"{payload['start']}")
    body = (
        "EDCS-Gate meeting request. Do not edit — processed automatically "
        "by Power Automate.\n\n"
        f"JIRA: {payload['jira_id']}\n"
        f"Automation: {payload['automation_name']}\n"
        f"When: {payload['start']} – {payload['end']} ({payload['timezone']})\n"
        f"Organizer: {payload['organizer_email']}\n"
        f"Attendees: {payload['attendees_semicolon']}\n\n"
        f"{MARKER_OPEN}{json.dumps(payload, separators=(',', ':'))}{MARKER_CLOSE}\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
              [settings.PA_TRIGGER_MAILBOX], fail_silently=False)
    return payload


# ── Meeting cancellation trigger ────────────────────────────────────
# The create-flow does not (yet) return the Graph event id, so the cancel
# The cancel flow correlates via the `[EDCSREF-<ref>]` marker stamped into the
# meeting subject at creation: Get events filtered with
# contains(subject,'EDCSREF-<ref>') -> Delete event. Robust against subject edits
# elsewhere in the string and against reschedules done in Outlook.

def build_cancel_payload(meeting):
    ref = meeting_ref(meeting)
    return {
        "version": 2,
        "action": "cancel",
        "meeting_id": str(meeting.id),
        "ref": ref,
        "search_marker": f"EDCSREF-{ref}",
        "graph_event_id": meeting.graph_event_id or "",
        "subject": meeting.subject,
        "jira_id": (meeting.validation_run.jira_id
                    if meeting.validation_run else ""),
        "automation_name": (meeting.validation_run.automation_name
                            if meeting.validation_run else ""),
        "start": meeting.start_at.astimezone(
            __import__("zoneinfo").ZoneInfo(meeting.timezone)
        ).strftime("%Y-%m-%dT%H:%M:%S"),
        "end": meeting.end_at.astimezone(
            __import__("zoneinfo").ZoneInfo(meeting.timezone)
        ).strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": meeting.timezone,
        "organizer_email": meeting.organizer.email or "",
    }


def send_meeting_cancel(meeting):
    """Send the [EDCS-CANCEL] trigger. Raises PAConfigError if mailbox unset."""
    if not settings.PA_TRIGGER_MAILBOX:
        raise PAConfigError(
            "PA_TRIGGER_MAILBOX is not set in .env — required to send the "
            "cancellation trigger to Power Automate.")
    payload = build_cancel_payload(meeting)
    subject = (f"{settings.PA_CANCEL_SUBJECT_PREFIX} "
               f"{payload['subject']} {payload['start']}")
    body = (
        "EDCS-Gate meeting CANCELLATION request. Do not edit — processed "
        "automatically by Power Automate.\n\n"
        f"Meeting: {payload['subject']}\n"
        f"JIRA: {payload['jira_id']}\n"
        f"Automation: {payload['automation_name']}\n"
        f"When: {payload['start']} – {payload['end']} ({payload['timezone']})\n\n"
        f"{MARKER_OPEN}{json.dumps(payload, separators=(',', ':'))}{MARKER_CLOSE}\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
              [settings.PA_TRIGGER_MAILBOX], fail_silently=False)
    return payload
