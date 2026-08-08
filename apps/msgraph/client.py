"""Microsoft Graph client — delegated tokens, organizer-only calls.

Every call here runs as the SIGNED-IN user against /me — the app never
touches another person's mailbox. Scopes: User.Read, Calendars.ReadWrite.

MOCK MODE: when GRAPH_CLIENT_ID is empty the client returns realistic
fake data so the whole app works before Azure registration is done.
"""
import logging
import uuid
import requests
import msal
from django.conf import settings
from .models import GraphToken

log = logging.getLogger(__name__)
GRAPH = "https://graph.microsoft.com/v1.0"


class GraphAuthRequired(Exception):
    """User must (re)connect their Microsoft account."""


# ── MSAL plumbing ──────────────────────────────────────────────────
def _msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        settings.GRAPH_CLIENT_ID,
        client_credential=settings.GRAPH_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.GRAPH_TENANT_ID}",
        token_cache=cache)


def _load_cache(user):
    cache = msal.SerializableTokenCache()
    tok, _ = GraphToken.objects.get_or_create(user=user)
    blob = tok.load()
    if blob:
        cache.deserialize(blob)
    return cache, tok


def _save_cache(cache, tok):
    if cache.has_state_changed:
        tok.store(cache.serialize())


def auth_url(state: str) -> str:
    return _msal_app().get_authorization_request_url(
        settings.GRAPH_SCOPES, state=state,
        redirect_uri=settings.GRAPH_REDIRECT_URI)


def redeem_code(user, code: str):
    cache, tok = _load_cache(user)
    result = _msal_app(cache).acquire_token_by_authorization_code(
        code, scopes=settings.GRAPH_SCOPES,
        redirect_uri=settings.GRAPH_REDIRECT_URI)
    if "error" in result:
        raise GraphAuthRequired(result.get("error_description", "auth failed"))
    _save_cache(cache, tok)
    return result


def _access_token(user) -> str:
    cache, tok = _load_cache(user)
    app = _msal_app(cache)
    accounts = app.get_accounts()
    if not accounts:
        raise GraphAuthRequired("No Microsoft account connected.")
    result = app.acquire_token_silent(settings.GRAPH_SCOPES, account=accounts[0])
    _save_cache(cache, tok)
    if not result or "access_token" not in result:
        raise GraphAuthRequired("Token refresh failed — reconnect Microsoft account.")
    return result["access_token"]


def _call(user, method, path, **kwargs):
    """Central Graph call with 429 Retry-After handling."""
    import time
    headers = {"Authorization": f"Bearer {_access_token(user)}"}
    for attempt in range(4):
        resp = requests.request(method, GRAPH + path, headers=headers,
                                timeout=30, **kwargs)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", "2")))
            continue
        resp.raise_for_status()
        return resp.json() if resp.content else {}
    resp.raise_for_status()


def is_connected(user) -> bool:
    if settings.GRAPH_MOCK:
        return True
    try:
        _access_token(user)
        return True
    except GraphAuthRequired:
        return False


# ── Calendar: organizer-only free/busy ─────────────────────────────
def get_busy_blocks(user, date, tz):
    """Return the ORGANIZER'S OWN busy blocks for a date:
    [(start_iso, end_iso), ...] in the given IANA timezone."""
    if settings.GRAPH_MOCK:
        # Fake: busy 10:00–10:30 every day so one demo slot disappears
        return [(f"{date}T10:00:00", f"{date}T10:30:00")]
    body = {
        "schedules": [user.email or user.username],
        "startTime": {"dateTime": f"{date}T00:00:00", "timeZone": tz},
        "endTime": {"dateTime": f"{date}T23:59:59", "timeZone": tz},
        "availabilityViewInterval": 30,
    }
    data = _call(user, "POST", "/me/calendar/getSchedule", json=body)
    blocks = []
    for sched in data.get("value", []):
        for item in sched.get("scheduleItems", []):
            if item.get("status") in ("busy", "oof", "tentative"):
                blocks.append((item["start"]["dateTime"][:19],
                               item["end"]["dateTime"][:19]))
    return blocks


# ── Teams meeting creation (invitations auto-sent by Exchange) ─────
def create_teams_meeting(user, subject, body_html, start_iso, end_iso, tz,
                         attendees):
    if settings.GRAPH_MOCK:
        fake = uuid.uuid4().hex[:12]
        return {"event_id": f"mock-{fake}",
                "join_url": f"https://teams.microsoft.com/l/meetup-join/mock/{fake}"}
    payload = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html},
        "start": {"dateTime": start_iso, "timeZone": tz},
        "end": {"dateTime": end_iso, "timeZone": tz},
        "attendees": [{"emailAddress": {"address": a}, "type": "required"}
                      for a in attendees],
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness",
        "transactionId": str(uuid.uuid4()),   # idempotent retry safety
    }
    data = _call(user, "POST", "/me/events", json=payload)
    return {"event_id": data.get("id", ""),
            "join_url": (data.get("onlineMeeting") or {}).get("joinUrl", "")}


def cancel_meeting(user, event_id, comment="Cancelled via EDCS-Gate"):
    if settings.GRAPH_MOCK:
        return
    _call(user, "POST", f"/me/events/{event_id}/cancel",
          json={"comment": comment})
