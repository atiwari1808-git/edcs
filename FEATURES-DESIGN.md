# Feature & Architecture Reference (current state)

This replaces the original planning document (customer name, terminate,
live progress, back button, meeting cancel/reschedule) — every one of
those has since shipped, several with a different final design than first
proposed. This doc describes what's actually running today.

## Core flow

Verify (real EDCS scanners, gated by RBAC `verification.execute`) → PASS →
Scheduler (tool-exclusive calendar, one booking per tool+date+slot, and one
active booking per **JIRA ID globally** across all tools) → Power Automate
email trigger creates the real Teams meeting → Dashboard (audit-tracked
cancel with mandatory reason).

## Validation & termination

Real Celery is optional. With `CELERY_TASK_ALWAYS_EAGER=True` (the
default), a threading-based dispatch runs both scanners in parallel inside
the request-handling process — still gives live per-scanner progress
polling and a working **Terminate** button (cooperative cancel flag,
checked at safe points between scanner steps; a cancelled run shows
**Cancelled**, not Failed, and is excluded from pass/fail scoring). Real
Celery (`False` + Redis) is a drop-in upgrade for cross-restart durability
and independent worker scaling — same code path either way.

## Scheduling — Power Automate email trigger (not Graph)

`SCHEDULER_MODE=powerautomate_email` is the supported default; Graph mode
exists in code as a dormant fallback only (blocked by tenant consent
policy originally, not revisited since). Booking sends a structured
trigger email; your Power Automate flow creates the Teams meeting. See
`POWERAUTOMATE-SETUP.md` for the full build guide, including:
- Plain-text markers (`###EDCS-JSON-START###`/`END###`) — angle-bracket
  markers were tried first and silently stripped by Exchange's HTML
  handling; don't reintroduce them.
- A unique `ref`/`[EDCSREF-...]` marker baked into every meeting subject
  and reused by the cancel flow to identify the right event.
- **Recommended cancel-lookup path: a SharePoint index list**, added
  specifically because the Outlook **"Get events"** action is blocked by
  Advanced Connector Policy/DLP on some tenants. A subject-search fallback
  is documented for tenants where Get events isn't blocked.
- Required vs. optional (CC) attendees are separate payload fields
  (`attendees_semicolon` / `cc_semicolon`) — CC is already wired to map to
  the Outlook action's Optional Attendees field.
- **Known limitation:** the Outlook-level meeting *organizer* is whichever
  account the flow's connection authenticates as — not the booking user.
  There's no channel to change this without direct Graph API access
  (which is exactly what this architecture avoids). The booking user is
  added as a required attendee instead.

## RBAC — fully dynamic, no hardcoded roles

`apps.rbac`: `Permission` (module+action, e.g. `schedules.cancel`) →
`Role` (admin-editable bundle) → `User` (many-to-many via `UserRole`,
effective access = union across all held roles). Enforced at **both**
layers — UI hides what's inaccessible, and every mutating endpoint
independently checks via `@require_permission(...)`, verified by testing
direct API calls that bypass the UI entirely. Manage roles at
`/manage/roles/` (or the Django admin User page's Roles inline) and
assign them at `/manage/users/`. See `RBAC-GUIDE.md`.

Four starter roles are seeded (`Admin`, `Scrum Master`, `Developer`,
`Viewer`) — fully editable, not fixed; only their *deletion* is blocked
(`is_system=True`) to prevent locking the app out of itself.

## Meeting cancellation — audit-tracked, mandatory reason

Cancelling from the dashboard requires a reason (Bootstrap modal, submit
blocked until filled) and requires the `schedules.cancel` permission —
this is a flat capability gate, not an ownership check: a user without
that permission can't cancel even their own booking. `cancelled_by`,
`cancelled_at`, `cancellation_reason` are stored and always visible in the
dashboard table; a cancelled row shows a disabled/greyed Cancel button
rather than removing the control. The `[EDCS-CANCEL]` Power Automate
trigger fires the same as before.

## Per-tool configuration

`MeetingTemplate` now has an optional `tool` FK — a tool-specific template
(subject/body/default attendees) is tried first, falling back to the one
global template (`tool=NULL`) if none exists for the booked tool. Subject
default: `Handover Call – {tool_name} | {jira_id} – {automation_name} [{ref}]`.

## Document/secret scanning tuning

Real EDCS engine (`vendor/edcs_core`), wired per `INTEGRATION.md`. Two
tuning surfaces admins should review before trusting scores:
- `mandatory_documents.yaml` — alias-based matching against real filenames;
  see `ERIDOC-MATCHING-TUNING-GUIDE.md`.
- `secret_rules.yaml` — named regex rules are the primary detection layer;
  the bundled `detect-secrets` plugin is **off by default**
  (`enable_detect_secrets_plugin: false`) after it was found to false-positive
  heavily on long file paths and numeric node/archive IDs.

## Known gaps / deliberately out of scope for now

- **No inbound mail-reading path in the app.** The Power Automate flows
  are one-way (app → PA). Capturing the real Graph event id back into
  `Meeting.graph_event_id` (for direct id-based cancel/reschedule without
  a SharePoint index) would need this built — flagged, not silently
  dropped, in case it's wanted later.
- **`meeting.edited`/`schedule.modified` audit actions** have no endpoint
  to hang them on yet — bookings are create/cancel only; slot/tool config
  changes go through Django admin's own separate history, not the app's
  `AuditLog`.
- **`SlotTemplate`/`WorkingHours`/`BlockedWeekday`/`BlockedTime`** models
  are unused leftovers from the pre-Handover-Scheduler design (organizer-
  Graph-calendar availability). Unregistered from the admin sidebar; data
  untouched in case of future revival.
