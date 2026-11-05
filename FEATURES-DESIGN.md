# Feature & Architecture Reference (current state)

This replaces the original planning document (customer name, terminate,
live progress, back button, meeting cancel/reschedule) — every one of
those has since shipped, several with a different final design than first
proposed. This doc describes what's actually running today.

## Core flow

Verify (real EDCS scanners, gated by RBAC `verification.execute`; pick a
**JIRA Type** and **Automation Type**, optional **ERIDOC Folder Path**) →
PASS → then one of two paths depending on the automation type:

- **Scheduling types** (`requires_scheduling=True`) → Scheduler
  (tool-exclusive calendar, one booking per tool+date+slot, and one active
  booking per **JIRA ID globally** across all tools) → Power Automate email
  trigger creates the real Teams meeting → Dashboard (audit-tracked
  cancel/reschedule with mandatory reason) → post-handover GO-live
  follow-ups/escalation until marked GO-live.
- **Document-only types** (`requires_scheduling=False`) → no meeting; a
  completion email goes to the tool's member list + requester + doc scrum
  master. The run lands on the dashboard's **"No Meeting Needed"** view and
  carries its own GO-live mark-off.

## JIRA Type — Story vs Enhancement

`adminconfig.JiraType` rows drive a dropdown on the Verify page (seed two:
Story with `requires_parent=False`, Enhancement with `requires_parent=True`).
For an **Enhancement** the form relabels the main JIRA field to **Parent
JIRA** and reveals a separate **Enhancement JIRA ID**. On the run,
`ValidationRun.jira_type` records the type; for an enhancement, `jira_id`
holds the enhancement id (the independent unit that gets scanned/scheduled)
and `parent_jira_id` holds the parent story, with `enhancement_jira_id`
mirroring `jira_id` so reports/exports can show it explicitly. Each
enhancement is verified and scheduled independently but stays linked to its
parent story.

## Automation Type — scheduling vs document-only

`adminconfig.AutomationType` rows carry `requires_scheduling` (the switch
between the two post-scan paths above) and an optional
`notification_emails` CC list added to every scan-completion notification
for that type. `ValidationRun.automation_type` + the
`ValidationRun.requires_scheduling` property decide whether a PASS offers a
booking or ends as a doc-only completion. Doc-only runs appear in the
dashboard's **No Meeting Needed** tab and in sheet 2 of the bookings
workbook.

## ERIDOC folder-link scanning

A run may carry an explicit `ValidationRun.eridoc_path`. Per tool,
`ToolConfig.eridoc_path_mode` is **REQUIRED** (the field must be filled) or
**OPTIONAL** (blank falls back to the original JIRA-name ERIDOC lookup).
The adapter (`apps/scanners/eridoc_adapter.py`) accepts:

1. A full ERIDOC web link carrying a folder object id (`…?locateId=0b004cff…`)
   → the scan is pinned to that exact folder, bypassing JIRA-name discovery.
2. A bare 16-char Documentum object id (`0b004cffd9ad177d`) → same as (1).
3. A Documentum folder path starting with `/` → scopes name-based discovery.
4. Blank → JIRA-name fallback, **only** when the tool does not mark the path
   as required.

A **non-blank path that is neither a recognisable id/link nor a `/`-path is
rejected** (`EridocPathError` → scanner ERROR), so a wrong link is never
silently ignored. `.zip` bundles are accepted: the engine's
"unsupported content / no validator" warning is suppressed for them while
the JIRA-ID naming/integrity checks still apply. See
`ERIDOC-MATCHING-TUNING-GUIDE.md`.

## Scrum Master attendee + dashboard column/filter

`scheduler.MeetingAttendee.Kind` now includes `SCRUM_MASTER` (alongside
DEVELOPER / CC / REQUIRED). Doc-only runs also store
`ValidationRun.doc_scrum_master_email`. The dashboard shows a Scrum Master
column and filters by it; the bookings workbook carries a **Scrum Masters**
column.

## Meeting reschedule — audit-tracked, notifies everyone

Alongside cancel, bookings can be **rescheduled**
(`apps/scheduler/views.py::reschedule_booking`,
`meetings/<id>/reschedule/`, gated by `schedules.edit`). Both cancel and
reschedule email all participants via `apps/notifications/handover_emails.py`
(`meeting_cancelled_notice` / `meeting_rescheduled_notice`), reusing the
same branded email shell as the scan-completion mails.

## Post-handover GO-live follow-ups + escalation

Once a handover's date has passed and the JIRA isn't yet marked GO-live,
two timed nudges fire (both counted from the day after the handover date):

- **Day 10 (default) — per-tool team reminder.**
  `adminconfig.HandoverFollowupConfig` (one per tool: `team_emails`,
  `go_live_reminder_day`) → "kindly move the JIRA to GO live" email to the
  tool team + organizer.
- **Day 15 (default) — global manager escalation.**
  `adminconfig.EscalationPolicy` (a single active global row:
  `manager_emails`, `escalation_day`, `cc_team`) → escalation to managers,
  optionally CC-ing the tool team + organizer.

`apps/scheduler/followup_service.py::run_handover_followups()` is idempotent
— each email fires at most once per meeting, guarded by
`Meeting.golive_reminder_sent_at` / `Meeting.escalation_sent_at` timestamps.
It is invoked from **both** the daily management command
(`python manage.py run_handover_followups`, the reliable path when
`CELERY_TASK_ALWAYS_EAGER=True`) and the Celery beat task
(`apps.scheduler.followup_tasks.dispatch_handover_followups`). See
`DEPLOYMENT.md` for the cron / Task Scheduler setup.

**Marking GO-live stops the reminders.** For scheduling runs,
`apps/scheduler/golive_views.py::mark_go_live` (`schedules.edit`, POST
`meetings/<id>/go-live/`) sets `Meeting.go_live_done/at/by` — only allowed
after the handover date has passed and not for cancelled/failed meetings.
For doc-only runs, `apps/validation/doc_only_go_live.py::mark_doc_go_live`
(POST `validations/<id>/go-live/`) sets the same fields on `ValidationRun`.

## Bookings Excel export

`apps/scheduler/services_bookings_workbook.py::bookings_workbook()` builds a
styled two-sheet workbook, gated behind `reports.export` and always scoped
to exactly the filters applied on the page (search / tool / status / JIRA
type / date range / scrum-master):

- **Sheet 1 "Handover Bookings"** — Organizer, Tool, Automation Type, JIRA
  Type, Customer, JIRA ID, Parent JIRA, Enhancement JIRA, Automation Name,
  Scrum Masters, Developers, CC, **Handover Initiated** (`created_at`),
  **Handover Date** (`start_at`), Slot, Status, **Cancelled / Rescheduled
  By**, **Reason**.
- **Sheet 2 "No Meeting Needed"** — the doc-only runs
  (`automation_type.requires_scheduling=False`) with their status/remarks;
  both date columns mirror the verification time since there's no meeting.

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

**Per-role daily quotas.** Each `Role` carries `max_meetings_per_day` and
`max_nmn_verifications_per_day` (blank/NULL = unlimited, `0` = fully
blocked, `N` = at most N per calendar day). Because access is the union of
a user's roles, the *most permissive* value wins
(`apps.rbac.permissions.user_daily_limit`). Edit the caps on the role form
at `/manage/roles/`. See `RBAC-GUIDE.md`.

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
- **`schedule.modified` audit action** has no dedicated endpoint — slot/tool
  config changes go through Django admin's own separate history, not the
  app's `AuditLog`. (Booking create/cancel/reschedule and GO-live marking
  *are* logged via `apps.audit.log.log_action`.)
- **`SlotTemplate`/`WorkingHours`/`BlockedWeekday`/`BlockedTime`** models
  are unused leftovers from the pre-Handover-Scheduler design (organizer-
  Graph-calendar availability). Unregistered from the admin sidebar; data
  untouched in case of future revival.
