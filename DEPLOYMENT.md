# EDCS-Gate / Handover Scheduler — Linux Deployment Guide

Power Automate email-trigger scheduling is the default and supported path
(no Azure AD app registration, no tenant consent needed). Graph mode still
exists in code (`SCHEDULER_MODE=graph`) as a dormant fallback only. This
guide covers the app as it stands today: real EDCS scanners, dynamic RBAC,
per-tool meeting templates, and the Bootstrap/PAMS-styled UI.

Two deployment paths: **A) bare-metal/systemd** on a Linux host and
**B) Docker Compose** (already in the repo).

---

## 1. What this app actually needs, and why

| Component | Needed for |
|---|---|
| Python **3.11** specifically | Django 4.2 doesn't support 3.13+; on very new distros (Ubuntu 26.04+) the default `python3` may already be 3.14 — install 3.11 explicitly, don't rely on the system default. Symptom if you get this wrong: `/admin/` throws `'super' object has no attribute 'dicts'` on every page. |
| **`git` (system package)** | The Bitbucket scanner shells out to `git clone` via GitPython. Missing this is the #1 real-world deploy failure — "Bad git executable," identical on a fresh Linux box or inside Docker. |
| **`libmagic1` (system package)** | `python-magic` (file-type sniffing in document scanning) needs this C library on Linux — the pip package alone does nothing without it. |
| PostgreSQL 15 | Production DB (SQLite is dev-only) |
| Redis 7 | Celery broker — **optional**; see §4 |
| Internal SMTP relay | Sends Power Automate trigger emails (create + cancel), reminders, account-activation mail. **Load-bearing** — without it, scheduling doesn't work at all. |
| Outbound network to ERIDOC + Bitbucket hosts | Real scanning (`DEMO_MODE=False`) |
| **No outbound network to Microsoft/Azure required** | Scheduling goes through your internal mail relay only |

## 2. Full current `.env` reference

```ini
# ── Core ──────────────────────────────────────────────────────────
SECRET_KEY=<long random value>
DEBUG=False                          # auto-enables HSTS + secure cookies
ALLOWED_HOSTS=handover.yourdomain.internal

# ── Database ────────────────────────────────────────────────────
DB_ENGINE=postgres
DB_NAME=edcs_gate
DB_USER=edcs
DB_PASSWORD=<strong password>
DB_HOST=<postgres host>
DB_PORT=5432

# ── Celery / Redis ────────────────────────────────────────────────
# True = threading fallback (no Redis needed) — live progress + Terminate
# still work, capped at one concurrent validation per gunicorn worker.
# False = real Celery (needs Redis + a worker process).
CELERY_TASK_ALWAYS_EAGER=False
CELERY_BROKER_URL=redis://<redis host>:6379/0
SCANNER_TIMEOUT_SECONDS=600

# ── Scanners ──────────────────────────────────────────────────────
DEMO_MODE=False
ERIDOC_REST_URL=https://erid2rest.internal.ericsson.com/d2rest
ERIDOC_REPOSITORY=eridoca
ERIDOC_USERNAME=svc-edcs
ERIDOC_PASSWORD=<real credential>
ERIDOC_VERIFY_TLS=true
# ERIDOC_CA_BUNDLE=/etc/ssl/certs/internal-ca.pem   # if TLS verification fails against your internal CA
BITBUCKET_USERNAME=svc-edcs
BITBUCKET_TOKEN=<real token>
BITBUCKET_ALLOWED_HOSTS=<your real Bitbucket host>   # NOT the bitbucket.xxx.com placeholder
COMPLIANCE_PASS_SCORE=90
SEVERITY_FAIL_THRESHOLD=HIGH
# MANDATORY_DOCS_FILE=/etc/edcs-gate/mandatory_documents.yaml   # optional override, see ERIDOC-MATCHING-TUNING-GUIDE.md
# SECRET_RULES_FILE=/etc/edcs-gate/secret_rules.yaml

# ── Scheduler mode — Power Automate email trigger (the supported path) ──
SCHEDULER_MODE=powerautomate_email
PA_TRIGGER_MAILBOX=edcs-gate-scheduler@ericsson.com   # a shared mailbox, not a personal inbox
PA_SUBJECT_PREFIX=[EDCS-GATE-MEETING]
PA_CANCEL_SUBJECT_PREFIX=[EDCS-CANCEL]

# ── Microsoft Graph — dormant fallback ─────────────────────────────
GRAPH_CLIENT_ID=
GRAPH_CLIENT_SECRET=
GRAPH_TENANT_ID=
GRAPH_REDIRECT_URI=https://handover.yourdomain.internal/auth/graph/callback
TOKEN_ENCRYPTION_KEY=

# ── Email — load-bearing, not just reminders ───────────────────────
EMAIL_HOST=<your internal SMTP relay>
EMAIL_PORT=25
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=False
DEFAULT_FROM_EMAIL=edcs-gate-noreply@ericsson.com
# Your Power Automate flow's sender-check condition must match this
# exact address, or the create/cancel flows will silently reject
# every trigger email.

# ── App ───────────────────────────────────────────────────────────
APP_TIMEZONE=Asia/Kolkata
```

---

## 3. Path A — Bare-metal / systemd on a Linux host

### 3.1 System packages

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv git libmagic1 \
    build-essential libpq-dev postgresql-client
# If python3.11 isn't in your distro's default repos (very new Ubuntu):
#   sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get update
#   sudo apt-get install -y python3.11 python3.11-venv
```

### 3.2 App user, code, virtualenv

```bash
sudo useradd -r -m -d /opt/edcs-gate -s /usr/sbin/nologin edcsgate
sudo -u edcsgate -H bash -c '
  cd /opt/edcs-gate
  python3.11 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r edcs_gate/requirements.txt
'
```
`requirements.txt` includes `-e ./vendor/edcs_core` — the real EDCS scanner
engine installs automatically in the same `pip install`.

### 3.3 Configure, migrate, seed

```bash
cd /opt/edcs-gate/edcs_gate
sudo -u edcsgate cp .env.example .env
sudo -u edcsgate nano .env

sudo -u edcsgate bash -c '
  source ../.venv/bin/activate
  python manage.py migrate
  python manage.py seed_defaults    # tools, daily slot, holidays, meeting template
  python manage.py seed_rbac        # permission catalogue + starter roles — idempotent
  python manage.py collectstatic --noinput
  python manage.py createsuperuser
'
```

Then, once logged in: review/customize starter roles at `/manage/roles/`
(or the Django admin User page's Roles inline), assign roles to real users
at `/manage/users/`, and if different tools need different default
attendees, add tool-specific rows at `/admin/adminconfig/meetingtemplate/`
(the one seeded row with no tool set is the global fallback — leave it).

### 3.4 systemd units

`/etc/systemd/system/edcs-gate-web.service`
```ini
[Unit]
Description=EDCS-Gate gunicorn
After=network.target postgresql.service

[Service]
User=edcsgate
WorkingDirectory=/opt/edcs-gate/edcs_gate
EnvironmentFile=/opt/edcs-gate/edcs_gate/.env
ExecStart=/opt/edcs-gate/.venv/bin/gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

If `CELERY_TASK_ALWAYS_EAGER=False` (real async), add worker + beat units
too — otherwise skip, the threading fallback handles everything in-process:

`/etc/systemd/system/edcs-gate-worker.service`
```ini
[Unit]
Description=EDCS-Gate Celery worker
After=network.target redis.service

[Service]
User=edcsgate
WorkingDirectory=/opt/edcs-gate/edcs_gate
EnvironmentFile=/opt/edcs-gate/edcs_gate/.env
ExecStart=/opt/edcs-gate/.venv/bin/celery -A config worker -l info --concurrency=4
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/edcs-gate-beat.service` — identical, but
`ExecStart=... celery -A config beat -l info` (exactly **one** instance).

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now edcs-gate-web edcs-gate-worker edcs-gate-beat
```

### 3.5 Reverse proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name handover.yourdomain.internal;
    ssl_certificate     /etc/ssl/certs/internal.pem;
    ssl_certificate_key /etc/ssl/private/internal.key;

    location /static/ { alias /opt/edcs-gate/edcs_gate/staticfiles/; }
    location /media/  { alias /opt/edcs-gate/edcs_gate/media/; }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## 4. Do you actually need Redis/Celery?

Not necessarily. `CELERY_TASK_ALWAYS_EAGER=True` runs validations via an
in-process threading fallback — still gives live per-scanner progress and
Terminate, just one concurrent validation per gunicorn worker (bump
`--workers` if that's a bottleneck), and no cross-restart task survival.
Move to real Celery when you need either of those.

---

## 5. Power Automate — the network-facing part of this deployment

Nothing in this app calls out to Microsoft or Azure directly. Scheduling
depends on: (1) this server's outbound SMTP to your internal relay, and
(2) your Power Automate flows watching `PA_TRIGGER_MAILBOX`, matching
`DEFAULT_FROM_EMAIL` in their sender-check condition. Build both the
create and cancel flows per `POWERAUTOMATE-SETUP.md` — note the cancel
flow's recommended path uses a **SharePoint index list** rather than
Outlook's "Get events" action, since that action is blocked by Advanced
Connector Policy/DLP on some tenants; confirm with your Power Platform
admin which connectors/actions are actually allowed before building.

---

## 6. Path B — Docker Compose

```bash
cp .env.example .env    # fill in per §2
docker compose up --build -d
docker compose exec web python manage.py seed_rbac
docker compose exec web python manage.py createsuperuser
```
(`migrate`, `seed_defaults`, and `seed_rbac` already run automatically in
the web container's startup command — `createsuperuser` still needs to be
run manually as shown.)

Dockerfile already installs `git` and `libmagic1` — if you're on an older
copy that doesn't, add both via `apt-get` before the `pip install` layer.

---

## 7. Production hardening checklist

- [ ] `DEBUG=False`, strong unique `SECRET_KEY`, exact `ALLOWED_HOSTS`
- [ ] Python **3.11** confirmed (`python --version` inside the venv/container)
- [ ] `BITBUCKET_ALLOWED_HOSTS` set to your **real** Bitbucket host, not the placeholder
- [ ] `git` and `libmagic1` present — confirm with `git --version` and `python -c "import magic"`
- [ ] SMTP relay reachable and tested — load-bearing for scheduling, not just reminders
- [ ] Power Automate: sender-check condition matches `DEFAULT_FROM_EMAIL` exactly; both create AND cancel flows built; cancel flow's SharePoint list (or confirmed-working Get-events alternative) in place
- [ ] `seed_rbac` run; starter roles reviewed at `/manage/roles/`; every real user has at least one role at `/manage/users/`
- [ ] Per-tool meeting templates/default attendees configured at `/admin/adminconfig/meetingtemplate/` if different tools need different attendee lists
- [ ] `enable_detect_secrets_plugin: false` in `secret_rules.yaml` unless you specifically want the noisier extra coverage
- [ ] `mandatory_documents.yaml` reviewed against your team's real document naming (see `ERIDOC-MATCHING-TUNING-GUIDE.md`)
- [ ] DB: revoke UPDATE/DELETE on `audit_auditlog` (append-only trail); nightly backups
- [ ] Reverse proxy: TLS, internal CA trust, rate-limit `POST /api/v1/validations`
- [ ] Monitoring: alert on validation `status=ERROR` and Power Automate flow run failures (checked in the Flow's own run history)

## 8. Smoke test (run after every deployment)

1. Sign in → Dashboard renders with KPI cards.
2. Verify Documents → a tool requiring Bitbucket (In-house/Enable/RPA) +
   real JIRA ID + real repo URL → confirm **both** scanners actually run
   (this exercises `git`/`libmagic1` — if either's missing, this fails
   with a scanner ERROR here, not silently later).
3. Terminate button appears while RUNNING; clicking it shows Cancelled.
4. Try booking the **same JIRA ID twice** → second attempt is rejected
   with the "already has a scheduled meeting" error.
5. Continue to Scheduler → book → confirmation shows "Meeting request
   sent" → trigger email lands in `PA_TRIGGER_MAILBOX` → Power Automate
   run history shows success → Teams invite arrives, subject includes
   tool name + automation name + unique ref.
6. Dashboard → Cancel → reason mandatory → row shows Cancelled By/Reason,
   Cancel button greys out → `[EDCS-CANCEL]` sent → Teams meeting actually
   disappears from attendees' calendars.
7. `/manage/roles/` loads for an Admin-role user, 403s for a Developer-role
   user hitting it directly by URL. `/admin/` → open a user → confirm the
   Roles inline is present and saves correctly.
