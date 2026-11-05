# Handover Scheduler (EDCS-Gate)

Release-readiness validation & handover-call scheduler for Ericsson tools
(In-House, Enable, MATE, RPA). Real ERIDOC document scanning + Bitbucket
code scanning run behind a validation gate; on PASS, the user either books a
handover call (a **Power Automate email trigger** creates the real Teams
meeting — no Azure AD app registration or Graph API access needed) **or**,
for document-only automation types, simply receives a completion email with
no meeting at all.

Access is governed by a fully dynamic **RBAC system** (roles + granular
permissions + per-role daily quotas, editable at `/manage/roles/` or Django
admin) — nothing about who can do what is hardcoded.

## 60-second local start

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.8–3.11
pip install -r requirements.txt        # installs the vendored EDCS scanner too (-e ./vendor/edcs_core)
cp .env.example .env                   # defaults: SQLite, eager Celery (no Redis needed), demo scanners
python manage.py migrate
python manage.py seed_defaults         # tools, daily slot, holidays, meeting template
python manage.py seed_rbac             # permission catalogue + starter roles (idempotent)
python manage.py createsuperuser
python manage.py runserver
```

Open http://localhost:8000 → sign in → **Verify Documents**.

⚠ Requires Python **3.8–3.11** — Django 4.2 doesn't support 3.13+. The
project was migrated to be Python 3.8-compatible (see
`requirements-production.txt` for the pinned, tested 3.8 lock and the
`offline_packages/` wheelhouse for air-gapped installs). If `/admin/`
throws a `'super' object has no attribute 'dicts'` error you're on an
unsupported interpreter (3.13+) — see the Python-version note in
DEPLOYMENT.md.

Demo behaviour (`DEMO_MODE=True`, until real scanning is wired):
- JIRA IDs ending in an **even** digit → ERIDOC passes; **odd** → missing
  Release Note (FAILED).
- Repo URLs containing "fail" → Bitbucket scanner fails.

## What's actually running today (vs. the original design)

The very first design used Microsoft Graph (delegated auth) to book on the
organizer's own calendar. That path was blocked by tenant consent policy
and is **not what's running now** — kept in the code as a dormant fallback
(`SCHEDULER_MODE=graph`) only. The supported, default path is:

| | |
|---|---|
| **Scheduling** | `SCHEDULER_MODE=powerautomate_email` — booking sends a structured trigger email; your Power Automate flow creates the real Teams meeting. See `POWERAUTOMATE-SETUP.md`. |
| **Scanning** | Real EDCS engine (`vendor/edcs_core`) — ERIDOC document compliance + Bitbucket secret/IP scanning. Toggle with `DEMO_MODE`. See `INTEGRATION.md`. |
| **Access control** | Dynamic RBAC (`apps.rbac`) — permissions are data, not code; roles also carry per-day booking/verification quotas. See `RBAC-GUIDE.md`. |
| **UI** | Bootstrap 5 + Bootstrap Icons, styled to match the internal PAMS tool's design language. |
| **Booking exclusivity** | One booking per **tool + date + slot**, first-come-first-served — *and* one active booking per **JIRA ID globally**, regardless of tool. |

## What's new since the first release

These features all shipped after the original docs were written and are
covered in detail in `FEATURES-DESIGN.md`:

- **JIRA Type (Story / Enhancement).** The Verify page now asks for a JIRA
  type (configurable in admin as `JiraType` rows). An **Enhancement** type
  relabels the main field to **Parent JIRA** and reveals a separate
  **Enhancement JIRA ID**; each enhancement is verified and scheduled
  independently but stays linked to its parent story.
- **Automation Types — scheduling vs document-only.** `AutomationType`
  rows carry a `requires_scheduling` flag. Scheduling types follow the
  normal *scan → book a call* flow; **document-only** types *scan → email a
  completion report* with no meeting (these land on the dashboard's "No
  Meeting Needed" view, and have their own GO-live mark-off).
- **ERIDOC folder-link scanning.** A run can carry an explicit
  **ERIDOC Folder Path** (a full ERIDOC link with `locateId`, a bare
  16-character Documentum object id, or a `/`-folder path). Per-tool,
  `ToolConfig.eridoc_path_mode` makes this **Required** or **Optional**
  (blank falls back to the JIRA-name lookup). A wrong/unrecognised path is
  rejected rather than silently ignored. See `ERIDOC-MATCHING-TUNING-GUIDE.md`.
- **Scrum Master attendee + dashboard column/filter.** Meetings track a
  dedicated Scrum Master attendee kind; the dashboard shows and filters by
  scrum master, and the Excel export carries a Scrum Masters column.
- **Mandatory cancellation reason + reschedule.** Cancelling requires a
  reason (audit-logged); bookings can also be **rescheduled**, and both
  actions email all participants.
- **Post-handover GO-live follow-ups + escalation.** Once a handover date
  passes and the JIRA isn't marked GO-live, the per-tool team is reminded
  (default day 10) and, if still open, managers are escalated (default day
  15). Mark GO-live from the dashboard to stop the reminders. Driven by a
  daily `run_handover_followups` command (or Celery beat). See `DEPLOYMENT.md`.
- **Bookings Excel export.** A styled two-sheet workbook (Handover Bookings
  + No Meeting Needed) gated behind the `reports.export` permission.
- **Per-role daily quotas.** Roles carry `max_meetings_per_day` and
  `max_nmn_verifications_per_day` (blank = unlimited, 0 = blocked). See
  `RBAC-GUIDE.md`.

## Where things are configured

| What | Where |
|---|---|
| Tools, scanners-per-tool, **ERIDOC path mode**, daily slots, holidays, meeting subject/body templates (incl. **per-tool** default attendees) | `/admin/` (Django admin) |
| **JIRA Types** (Story / Enhancement) and **Automation Types** (scheduling vs doc-only, CC notification emails) | `/admin/adminconfig/` |
| **Handover follow-up** recipients & day offsets (per tool), **Escalation policy** (global managers & day offset) | `/admin/adminconfig/` |
| Roles, granular permissions & **per-day quotas** | `/manage/roles/` (or the Django admin User page's Roles inline) |
| Assign roles to users | `/manage/users/` |
| ERIDOC mandatory-document checklist | `vendor/edcs_core/config/mandatory_documents.yaml` — see `ERIDOC-MATCHING-TUNING-GUIDE.md` before relying on compliance scores |
| Secret-scanning rules | `vendor/edcs_core/config/secret_rules.yaml` |

## Docs in this repo

- `DEPLOYMENT.md` — Linux deployment (bare-metal/systemd and Docker Compose), full `.env` reference, Python 3.8 / offline-install notes, the daily follow-up job, hardening checklist
- `POWERAUTOMATE-SETUP.md` — build the create + cancel Power Automate flows, click by click
- `INTEGRATION.md` — how the vendored EDCS scanner engine is wired in (incl. the ERIDOC folder-link scan)
- `ERIDOC-MATCHING-TUNING-GUIDE.md` — tuning the document-matching checklist against your team's real naming
- `RBAC-GUIDE.md` — the permission system's architecture, per-day quotas, and how to extend it
- `FEATURES-DESIGN.md` — current architecture/feature reference (what's built, why, and known limitations)

A now-historical upgrade-log doc (`V9-CUMULATIVE-UPGRADE-GUIDE.md`)
describes a past version-to-version patch that's already been applied —
safe to delete, kept only if you want the history.
