# EDCS-Gate — Fix bundle (ERIDOC required-path, .zip, report/email polish, User Guide)

This bundle fixes 5 things you reported and adds a User Guide.

## What changed & why

1. **ERIDOC "required path" no longer silently falls back to JIRA-ID search.**
   - `apps/scanners/eridoc_adapter.py` — `run()` now takes `required=`. A blank
     path when required, OR a non-blank path that is neither a valid folder
     link/id nor a `/`-path, now raises `EridocPathError` (a clear, non-retryable
     error) instead of falling back to JIRA-name discovery.
   - `apps/validation/tasks.py` — passes `required=` from the tool's
     `eridoc_path_mode == "REQUIRED"`, and surfaces the path error message
     verbatim on the Verify page, report and email.

2. **`.zip` is accepted in ERIDOC.** The "no content validator for .zip /
   unsupported content" warning is suppressed for `.zip`, while the JIRA-ID
   naming check and integrity checks still apply. (`eridoc_adapter.py`)

3. **Human-readable "Suggested fix" wording** (single source of truth in
   `apps/reports/context.py → humanize_fix()`), used by the report, PDF and email:
   - Doc Folder Missing → "Create the project folder in ERIDOC and upload all mandatory documents."
   - Secret → "Move to Database/.env injected at runtime; rotate the exposed value."
   - IPv4 → "Move IPs to configuration/database or static sheet; never hardcode."
   (plus sensible messages for the other categories.)

4. **Report/email cosmetics fixed** (`apps/notifications/email.py`):
   - The literal `&amp;` in "Scanner Results &amp; Issues Found" (double-escape) → now a real `&`.
   - Internal rule codes like `(EDCS-DOC-001)` are no longer shown to users.

5. **Full PDF report is always generated before the email and attached.**
   (unchanged from the previous bundle — `tasks.py` + `email.py`.)

## New: in-app User Guide + downloadable PDF
- `apps/guide/` (views + urls), `templates/guide.html`, `templates/guide_pdf.html`.
- Navbar "Guide" link (in `templates/base.html`) and a "Download PDF" button on the guide page.
- Guide styling appended to `static/css/app.css`.

---

## Files in this bundle

| File | Apply |
|------|-------|
| `apps/scanners/eridoc_adapter.py` | replace whole file |
| `apps/validation/tasks.py` | replace whole file |
| `apps/reports/context.py` | replace whole file |
| `apps/notifications/email.py` | replace whole file |
| `apps/guide/__init__.py`, `views.py`, `urls.py` | new files (copy the folder) |
| `templates/guide.html`, `templates/guide_pdf.html` | new files |
| `templates/base.html` (from the UI bundle) | replace — adds the Guide navbar link |
| `static/css/app.css` (from the UI bundle) | replace — adds Guide styling |

> Note: `base.html` and `app.css` also live in the earlier UI-redesign bundle;
> use the versions shipped there (they now include the Guide link + styles).

## Two small wiring edits (one-time)

**A. Register the Guide URLs** — in `config/urls.py`, add one include:

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.validation.urls")),
    path("", include("apps.scheduler.urls")),
    path("", include("apps.rbac.urls")),
    path("", include("apps.guide.urls")),          # <-- add this line
    path("auth/graph/", include("apps.msgraph.urls")),
]
```

**B. Add a Help button on the Verify page** — in `templates/verify.html`,
replace the page heading:

```html
<h1><i class="bi bi-clipboard2-check-fill" style="color:var(--indigo);font-size:1.1rem;margin-right:8px"></i>Verify Documents</h1>
```
with:
```html
<div class="guide-head">
  <h1><i class="bi bi-clipboard2-check-fill" style="color:var(--indigo);font-size:1.1rem;margin-right:8px"></i>Verify Documents</h1>
  <a href="/guide/" class="btn btn-secondary guide-dl"><i class="bi bi-life-preserver"></i> Help &amp; Guide</a>
</div>
```

---

## Backup first (WSL)
```bash
cd ~/Docker_project/edcs-gate-project/edcs_gate
BK=~/edcs-backup-$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"
cp --parents apps/scanners/eridoc_adapter.py apps/validation/tasks.py \
   apps/reports/context.py apps/notifications/email.py \
   templates/base.html templates/verify.html static/css/app.css config/urls.py "$BK"/
echo "Backup: $BK"
```
Restore: `cp -rf <BK>/apps <BK>/templates <BK>/static <BK>/config ~/Docker_project/edcs-gate-project/edcs_gate/`

## Apply
```bash
SRC=/mnt/c/Users/eihwatb/Downloads/edcs-verdict-fix
UI=/mnt/c/Users/eihwatb/Downloads/edcs-ui-redesign
DST=~/Docker_project/edcs-gate-project/edcs_gate

cp "$SRC/apps/scanners/eridoc_adapter.py" "$DST/apps/scanners/eridoc_adapter.py"
cp "$SRC/apps/validation/tasks.py"        "$DST/apps/validation/tasks.py"
cp "$SRC/apps/reports/context.py"         "$DST/apps/reports/context.py"
cp "$SRC/apps/notifications/email.py"     "$DST/apps/notifications/email.py"
cp -r "$SRC/apps/guide"                   "$DST/apps/"
cp "$SRC/templates/guide.html"            "$DST/templates/guide.html"
cp "$SRC/templates/guide_pdf.html"        "$DST/templates/guide_pdf.html"
cp "$UI/templates/base.html"              "$DST/templates/base.html"
cp "$UI/static/css/app.css"               "$DST/static/css/app.css"
# then do wiring edits A (config/urls.py) and B (verify.html) above
cd "$DST" && python manage.py collectstatic --noinput
```
No new migrations are required (`apps/guide` has no models). Restart the app
(and the worker process that runs scans) and hard-refresh.

## Verify it worked
- Run a verification for an ERIDOC-required tool with a **wrong** ERIDOC link:
  the ERIDOC card ends as **ERROR** with the clear "could not be recognised"
  message (never "Running"), overall verdict is ERROR, no Schedule button.
- Upload a `.zip` named `<JIRA-ID>_*.zip`: no "unsupported content" warning.
- Report/email: "Scanner Results & Issues Found" shows a real `&`, no `(EDCS-…)`
  codes, and the suggested-fix column uses the plain wording above.
- Open **Guide** in the navbar → click **Download PDF**.

---

## Round: Guide upgrade + unified Users page + configurable default role

### Files in this round
Backend (this bundle → project root):
- `apps/guide/views.py` — Guide now reads the **live mandatory-documents** list from the scanner checklist (`config/mandatory_documents.yaml`), with graceful fallback.
- `apps/rbac/views.py` — unified **Users hub** (`user_roles`) + `set_default_role`; all role CRUD preserved.
- `apps/rbac/urls.py` — adds `manage/users/default-role/`.
- `apps/rbac/context_processors.py` — NEW: `pending_activation_count` for the navbar dot.
- `apps/accounts/views.py` — self-register grants the **configurable default role** (Developer out of the box); activation gated by `users.create`; new `deactivate_user`; dashboard no longer builds the pending panel.
- `apps/accounts/urls.py` — adds `accounts/<id>/deactivate/`.
- `templates/guide.html`, `templates/guide_pdf.html` — mandatory-docs table + one-line formats note (.zip included).
- `templates/rbac/user_roles.html` — the unified Users page (Activations / Users & roles / Roles tabs + default-role selector + role-assign modal).

UI (ui-redesign bundle → project root):
- `templates/base.html` — navbar "Roles" → **"Users"** with the pending-activation dot.
- `templates/dashboard.html` — pending-activation panel removed (moved to Users page).
- `static/css/app.css` — Users tabs, notification dot, semantic badges, `.btn-outline`, `.form-select`, Guide additions.

### One-time wiring (settings.py)
Register the context processor so the navbar dot shows on every page:
```python
TEMPLATES = [{
    # ...
    "OPTIONS": {"context_processors": [
        # ...existing...
        "apps.rbac.context_processors.pending_activations",
    ]},
}]
```
No new migrations (uses existing `AppSetting`, `UserRole`, and permission rows).
After a fresh pull, run `python manage.py seed_rbac` once so the "Developer" role exists as the default.

### Verify
- Register a new account → it appears under **Users → Activations** with a navbar dot; on activation it holds the **Developer** role.
- Change the default role on the Users page → next registration uses it.
- Grant a role only `users.create` → that holder can activate but sees no deactivate/role-assign controls.
- Open the Guide → the mandatory-documents table matches `mandatory_documents.yaml`; Download PDF works.
