# EDCS-Gate — GO-live Follow-up/Escalation + Cancel/Reschedule Notices

Two additive features. Nothing in the existing working flows (book, cancel,
reschedule, verify, role limits, dashboard columns/sorting) is altered — every
new file is self-contained, and the few touch points are small inserts.

## Feature 1 — Post-handover GO-live follow-up + escalation
- Once a handover date passes and the JIRA is not yet GO-live, a **day-N** (default 10)
  reminder emails the **per-tool team**: "Handover completed on <date>. Kindly
  move JIRA <id> to GO live."
- If still not GO-live by **day-M** (default 15), a second email escalates to the
  **global manager list**.
- All recipients + day-offsets are configurable in **Django admin**:
  - Per tool: Adminconfig → "Handover follow-up config (per tool)" (team emails + GO-live day).
  - Global: Adminconfig → "Escalation policy (global)" (manager emails + escalation day).
- A **Mark GO-live** button on the dashboard stops follow-ups once someone marks it done.

## Feature 2 — Cancel / Reschedule participant notices
- On cancel: all participants get a branded "Handover cancelled" email (with reason + details).
- On reschedule: all participants get a "Handover rescheduled" email showing old → new date/slot.

---

## Files in this package (copy into your working copy at the same paths)

New, self-contained (drop in as-is):
- `apps/adminconfig/followup_models.py`
- `apps/adminconfig/followup_admin.py`
- `apps/notifications/handover_emails.py`
- `apps/scheduler/followup_service.py`     (the idempotent daily engine)
- `apps/scheduler/followup_tasks.py`       (Celery beat task)
- `apps/scheduler/golive_views.py`         (Mark GO-live view)
- `apps/scheduler/management/commands/run_handover_followups.py`  (+ the two `__init__.py`)
- `config/celery.py`                       (full replacement — adds the daily beat entry)

Insert snippets (see INTEGRATION_SNIPPETS.md — because these files differ between
your GitHub main and your working copy):
- `apps/adminconfig/models.py`   → 1 import line
- `apps/adminconfig/admin.py`    → 1 import line
- `apps/scheduler/models.py`     → paste `_MEETING_FIELDS_SNIPPET.py` block into class Meeting
- `apps/scheduler/urls.py`       → 1 import + 1 path
- `apps/scheduler/views.py`      → cancel notice (E1) + reschedule notice (E2)
- `templates/dashboard.html`     → Mark GO-live button (F)

---

## Apply steps

1. Copy the new files above into your project (same paths). Do NOT overwrite
   your working `views.py` / `urls.py` / `models.py` / `dashboard.html` — apply
   the snippets in INTEGRATION_SNIPPETS.md instead.
2. Copy `config/celery.py` (full replacement — the only change vs your baseline
   is the added `handover-golive-followups` beat entry and the crontab import).
3. Add the two import lines (A, B) and the Meeting fields (C).
4. Make + run migrations (adds the 5 Meeting fields + the 2 config tables):
   ```
   python manage.py makemigrations scheduler adminconfig
   python manage.py migrate
   ```
   (Using makemigrations avoids guessing your current migration numbers.)
5. Wire the URL (D), the two view notices (E), and the dashboard button (F).
6. In Django admin, create:
   - one **Handover follow-up config** per tool (team emails + GO-live day, default 10),
   - one **Escalation policy (global)** (manager emails + escalation day, default 15).

## Scheduling the daily job — pick ONE (both are provided)

Your default is `CELERY_TASK_ALWAYS_EAGER=True` (thread mode), where **Celery
beat does not run**. So:

- **If you run a real Celery worker + beat** (`CELERY_TASK_ALWAYS_EAGER=False`,
  Redis up): nothing else to do — the `handover-golive-followups` beat entry in
  `config/celery.py` fires daily at 03:30.
- **Otherwise (default deployment): use the management command via a scheduler.**
  - Linux cron (daily 03:30):
    ```
    30 3 * * *  cd /path/to/edcs && /path/to/venv/bin/python manage.py run_handover_followups >> /var/log/edcs_followups.log 2>&1
    ```
  - Windows Task Scheduler: daily action →
    `python manage.py run_handover_followups` in the project dir.

The command and the beat task call the **same idempotent engine**, so running
both is harmless — each email fires at most once per meeting (guarded by
`golive_reminder_sent_at` / `escalation_sent_at`). Run it manually any time to test:
```
python manage.py run_handover_followups
```

## Avoiding double emails on reschedule (important)

Your v1 `reschedule_booking` cancels the old meeting via the PA `[EDCS-CANCEL]`
trigger. If it internally calls `cancel_booking`, the E1 cancellation email
would fire in addition to the E2 reschedule email. To avoid that:
- Keep E1 only in the **dashboard cancel** path, and
- In the reschedule path, send **only** the reschedule notice (E2).
If your reschedule reuses `cancel_booking`, gate E1 behind a check like
`if "Rescheduled to" not in reason:` (your reschedule sets the old meeting's
cancellation_reason to "Rescheduled to …"), so the plain cancellation email is
skipped for reschedules.

## Notes / assumptions
- "Handover completed" = the meeting's booking date is strictly in the past.
- Only meetings in REQUESTED/CONFIRMED/PENDING and not GO-live are scanned;
  cancelled/failed meetings are ignored.
- GO-live reminders need `SITE_URL` unset-safe (emails don't rely on links).
- Emails use your existing branded shell (`_email_wrapper`/`_safe_send`) and the
  configured SMTP relay (console backend in dev), so they never raise into the
  request path.
