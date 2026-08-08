# Handover Scheduler (EDCS-Gate)

Release-readiness validation & handover-call scheduler for Ericsson tools
(In-House, Enable, MATE, RPA). Real ERIDOC document scanning + Bitbucket
code scanning run behind a validation gate; on PASS, the user books a
handover call, and a **Power Automate email trigger** creates the real
Teams meeting — no Azure AD app registration or Graph API access needed.

Access is governed by a fully dynamic **RBAC system** (roles + granular
permissions, editable at `/manage/roles/` or Django admin) — nothing about
who can do what is hardcoded.

## 60-second local start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # installs the vendored EDCS scanner too (-e ./vendor/edcs_core)
cp .env.example .env                   # defaults: SQLite, eager Celery (no Redis needed), demo scanners
python manage.py migrate
python manage.py seed_defaults         # tools, daily slot, holidays, meeting template
python manage.py seed_rbac             # permission catalogue + starter roles (idempotent)
python manage.py createsuperuser
python manage.py runserver
```

Open http://localhost:8000 → sign in → **Verify Documents**.

⚠ Requires Python **3.11** specifically — Django 4.2 doesn't support 3.13+
(see the Python-version note in DEPLOYMENT.md if `/admin/` throws a
`'super' object has no attribute 'dicts'` error).

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
| **Access control** | Dynamic RBAC (`apps.rbac`) — permissions are data, not code. See `RBAC-GUIDE.md`. |
| **UI** | Bootstrap 5 + Bootstrap Icons, styled to match the internal PAMS tool's design language. |
| **Booking exclusivity** | One booking per **tool + date + slot**, first-come-first-served — *and* one active booking per **JIRA ID globally**, regardless of tool. |

## Where things are configured

| What | Where |
|---|---|
| Tools, scanners-per-tool, daily slots, holidays, meeting subject/body templates (incl. **per-tool** default attendees) | `/admin/` (Django admin) |
| Roles & granular permissions | `/manage/roles/` (or the same data via the Django admin User page's Roles inline) |
| Assign roles to users | `/manage/users/` |
| ERIDOC mandatory-document checklist | `vendor/edcs_core/config/mandatory_documents.yaml` — see `ERIDOC-MATCHING-TUNING-GUIDE.md` before relying on compliance scores |
| Secret-scanning rules | `vendor/edcs_core/config/secret_rules.yaml` |

## Docs in this repo

- `DEPLOYMENT.md` — Linux deployment (bare-metal/systemd and Docker Compose), full `.env` reference, hardening checklist
- `POWERAUTOMATE-SETUP.md` — build the create + cancel Power Automate flows, click by click
- `INTEGRATION.md` — how the vendored EDCS scanner engine is wired in
- `ERIDOC-MATCHING-TUNING-GUIDE.md` — tuning the document-matching checklist against your team's real naming
- `RBAC-GUIDE.md` — the permission system's architecture and how to extend it
- `FEATURES-DESIGN.md` — current architecture/feature reference (what's built, why, and known limitations)

A now-historical upgrade-log doc (`V9-CUMULATIVE-UPGRADE-GUIDE.md`)
describes a past version-to-version patch that's already been applied —
safe to delete, kept only if you want the history.
