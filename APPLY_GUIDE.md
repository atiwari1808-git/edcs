# EDCS-Gate — Batch 2: Complete Drop-in Files

These are **complete files**, not snippets. Each file below **replaces** the
one at the same path in your repo. No hand-pasting of code fragments.

Baseline: these files were built directly on top of your current GitHub `main`
(confirmed to match your running app), and they preserve every batch-1 fix
already in `main`.

## What each requirement maps to

1. **ERIDOC folder path field** — `adminconfig/models.py` (`ToolConfig.eridoc_path_mode`),
   `validation/models.py` (`ValidationRun.eridoc_path`), `verify.html`,
   `validation/views.py`, `validation/services.py`, `validation/tasks.py`,
   `scanners/eridoc_adapter.py`.
2. **Story / Enhancement JIRA type (with Parent JIRA)** — `adminconfig/models.py`
   (`JiraType`), `adminconfig/admin.py`, `validation/models.py`
   (`jira_type`, `parent_jira_id`, `enhancement_jira_id`), `verify.html`,
   `validation/views.py`, `validation/services.py`, plus dashboard columns.
3. **Nomenclature & quality guidelines** — `docs/NOMENCLATURE_AND_QUALITY_GUIDELINES.md`.
4. **Cancellation-reason validation (no NA/None/junk)** — `scheduler/reason_validation.py`,
   `scheduler/views.py`, client-side mirror in `dashboard.html`.
5. **Scrum Master column + filter + auto-scope** — `scheduler/services.py`,
   `accounts/views.py`, `dashboard.html` (Excel export already carries the
   Scrum Masters column).

## File-to-path map (copy over your repo)

| File in this zip | Repo path |
|---|---|
| apps/adminconfig/models.py | apps/adminconfig/models.py |
| apps/adminconfig/admin.py | apps/adminconfig/admin.py |
| apps/validation/models.py | apps/validation/models.py |
| apps/validation/views.py | apps/validation/views.py |
| apps/validation/services.py | apps/validation/services.py |
| apps/validation/tasks.py | apps/validation/tasks.py |
| apps/scanners/eridoc_adapter.py | apps/scanners/eridoc_adapter.py |
| apps/scheduler/reason_validation.py | apps/scheduler/reason_validation.py (NEW) |
| apps/scheduler/views.py | apps/scheduler/views.py |
| apps/scheduler/services.py | apps/scheduler/services.py |
| apps/accounts/views.py | apps/accounts/views.py |
| templates/verify.html | templates/verify.html |
| templates/dashboard.html | templates/dashboard.html |
| docs/NOMENCLATURE_AND_QUALITY_GUIDELINES.md | docs/NOMENCLATURE_AND_QUALITY_GUIDELINES.md (NEW) |

## Apply steps

### 0. Back up (so you can roll back)
```bash
git checkout -b batch2-apply
git stash            # only if you have uncommitted local edits you want to keep
```

### 1. Copy the files in
Copy each file to the matching repo path (table above), overwriting.

### 2. Generate migrations LOCALLY (do NOT hand-write them)
This avoids the "nonexistent parent node" / phantom-migration errors from
before — `makemigrations` builds migrations that match *your* actual history.

```bash
python manage.py makemigrations adminconfig validation
```
Expected — two new migrations, roughly:
- `adminconfig`: add `JiraType`, add `ToolConfig.eridoc_path_mode`
- `validation`: add `ValidationRun.eridoc_path`, `jira_type`, `parent_jira_id`, `enhancement_jira_id`

> If instead it errors on a missing parent node, you still have an orphaned
> unapplied migration from the earlier sessions. Fix with:
> ```bash
> python manage.py showmigrations adminconfig validation
> ```
> Delete any **unapplied** `00xx_*.py` in those apps' `migrations/` folders that
> reference a parent that no longer exists, then re-run `makemigrations`.

### 3. Apply
```bash
python manage.py migrate
```

### 4. Seed the JIRA types (so the dropdown isn't empty)
```bash
python manage.py shell -c "
from apps.adminconfig.models import JiraType
JiraType.objects.get_or_create(key='STORY', defaults=dict(display_name='Story', requires_parent=False, sort_order=1))
JiraType.objects.get_or_create(key='ENHANCEMENT', defaults=dict(display_name='Enhancement', requires_parent=True, sort_order=2))
print('JIRA types seeded')
"
```

### 5. (Optional) Set ERIDOC path mode per tool
Default is OPTIONAL for every tool. To make the field mandatory for a tool:
```bash
python manage.py shell -c "
from apps.adminconfig.models import ToolConfig
ToolConfig.objects.filter(key='IN_HOUSE').update(eridoc_path_mode='REQUIRED')
print('done')
"
```
Or set it in Django admin → Tool configs.

### 6. Restart & verify
```bash
python manage.py collectstatic --noinput   # if you serve static
# restart your app / gunicorn / runserver
```

## 7. Verification checklist
- **Verify page**: JIRA Type dropdown appears. Pick **Enhancement** → the
  "JIRA ID" label changes to **Parent JIRA ID** and an **Enhancement JIRA ID**
  field appears (required). Pick **Story** → single JIRA ID field, as before.
- **Verify page**: for a tool whose scanners include ERIDOC, an **ERIDOC Folder
  Path** field shows. If that tool is set to REQUIRED, Run stays disabled until
  it's filled; if OPTIONAL, blank is allowed.
- **Dashboard**: new **JIRA Type** and **Scrum Master** columns. New **JIRA
  Type** filter. Search box now also matches Scrum Master email.
- **Dashboard (as a non-admin / scrum master)**: you see only handovers where
  your email is the Scrum Master, with a banner + "View all handovers" link.
- **Cancel a meeting**: entering `NA`, `None`, `test`, `....`, or `aaaa` is
  rejected both in the browser and on the server; a real reason is accepted.
- **Download Excel**: JIRA Type / Parent JIRA / Enhancement JIRA and Scrum
  Masters columns are present on both sheets.
- `python manage.py makemigrations` prints **"No changes detected."**

## Rollback
```bash
git checkout main -- apps templates docs   # restore code
python manage.py migrate adminconfig <previous_number>
python manage.py migrate validation <previous_number>
```
(Use the numbers shown by `showmigrations` *before* step 2. The new fields are
additive/nullable, so unapplying is safe.)
