# Dynamic RBAC — Architecture, Files, and Deployment Guide

Built and fully tested (9 test groups, all passing) on top of your v12/v13
project. This is additive — every existing feature (validation, scheduling,
PA email triggers, dashboard) keeps working; the previous coarse
Admin/Scrum Master/Viewer CharField is now backed by a real, editable
permission system, and existing users are auto-migrated onto it.

---

## 1. The data model

```
Permission(module, action, codename["module.action"], description)
Role(name, description, is_system, permissions M2M→Permission via RolePermission)
RolePermission(role, permission)                         — join table
UserRole(user, role, assigned_by, assigned_at)            — join table, audit-aware
User.roles = M2M(Role, through=UserRole)                  — a user may hold MULTIPLE roles
```

A user's **effective permissions = the union of every role they hold**.
Superusers implicitly hold every permission (Django's standard admin
escape hatch) — kept deliberately separate from this table so raw
`/admin/` access and app-level RBAC don't get tangled together.

Nothing is hardcoded: the full permission catalogue lives in
`apps/rbac/permissions.py::PERMISSION_CATALOGUE` as a plain list of
`(module, action, description)` tuples. Adding a new module or action later
is a one-line addition there + re-running `seed_rbac` — no migration, no
other code change. New **roles** need zero code at all — they're created
entirely through the UI.

### Seeded starter roles (`is_system=True` — can't be deleted, CAN be edited)
| Role | Notable permissions |
|---|---|
| **Admin** | Every permission in the catalogue |
| **Scrum Master** | verification (view/create/execute), reports (view/download/export), schedules (view/create/edit/cancel), settings.view |
| **Developer** | dashboard/verification/reports/schedules — **view only** |
| **Viewer** | Same as Developer (kept distinct in case you want to diverge them later) |

Existing users are migrated automatically: `ADMIN→Admin`, `SCRUM_MASTER→Scrum
Master`, `VIEWER→Viewer` (self-registered users default to Scrum Master, matching
the old behavior). This migration is **idempotent** — safe to re-run.

---

## 2. Enforcement — both layers, tested independently

**UI layer** (`perms_set` in every template, via `apps.rbac.context_processors.permissions`):
```django
{% if "schedules.cancel" in perms_set %}<button>Cancel</button>{% endif %}
```

**Server layer** (the actual security boundary):
```python
@require_permission("verification.execute")
def start(request): ...
```
`require_permission` returns **403 JSON** for `/api/` paths, or renders
`403.html` for full pages — either way, **independent of what the UI showed**.

This was explicitly tested: a Developer's *direct POST* to
`/api/v1/validations` (bypassing the disabled button entirely) is rejected
403, and a Developer's *direct POST* to a cancel URL is rejected 403 too —
confirming enforcement isn't just cosmetic.

---

## 3. Role Management UI (new, at `/manage/roles/`)

- **List** — every role, permission count, user count, Edit/Clone/Delete
- **Create/Edit** (`/manage/roles/new/`, `/manage/roles/<id>/edit/`) —
  permissions rendered as checkboxes **grouped by module** (Dashboard,
  Verification, Reports, Schedules, Users, Roles, Settings), with a
  select-all/clear link per group
- **Clone** — duplicates a role's full permission set under an
  auto-suffixed name (`"X (copy)"`, `"X (copy) 2"`, ...), redirects
  straight into editing the new copy
- **Delete** — blocked with a clear message if the role is a starter role,
  or if any user currently holds it (prevents silently orphaning users)
- **Assign to Users** (`/manage/users/`) — one row per user, checkboxes for
  every role, save per row; a user can hold several roles at once

All five actions require the matching `roles.*` permission themselves —
including bootstrapping: only someone with `roles.assign` can grant roles
to begin with (superusers always can, as the escape hatch).

---

## 4. Meeting cancellation — mandatory reason (Features 5 & 6)

Clicking **Cancel meeting** on the dashboard now opens a **Bootstrap modal**
(reusing the Bootstrap 5 already loaded in `base.html` — no new dependency)
requiring a reason before the form can submit at all (`required` textarea).
On confirm:
- `Meeting.cancelled_by`, `cancelled_at`, `cancellation_reason` are set
- The `[EDCS-CANCEL]` Power Automate trigger still fires exactly as before
- An `AuditLog` row is written (`action="meeting.cancelled"`, reason in `detail`)

**Dashboard changes (Feature 6):** once a booking is `Cancelled`, its row's
action column **no longer shows a Cancel button** (nothing to do) — instead
two new columns, **always present**, show **Cancelled By** and
**Cancellation Reason** for cancelled rows (and `—` for everything else).
The red "Cancelled" badge was already in place from the earlier visual
redesign.

The Cancel button itself now also requires `schedules.cancel` — meaning
this is a genuinely **flat capability gate**, not an ownership check: a
user without `schedules.cancel` can't cancel even their own booking. This
is a deliberate behavior change from before (previously: owner OR admin
could always cancel their own). If you'd rather keep an "always allowed to
cancel your own" carve-out alongside the permission system, say so — it's
a small addition to the view.

---

## 5. Audit trail (Feature 7)

`AuditLog` (existing table) gained three columns: `action`, `module`,
`detail` — nullable/blank, so old rows stay valid. Two logging paths now
coexist:

1. **`AuditMiddleware`** (unchanged) — still logs every mutating HTTP
   request generically (method/path/status/ip), automatically.
2. **`apps.audit.log.log_action(user, action, module, detail)`** — called
   explicitly at meaningful business-event moments, giving a human-readable
   trail alongside the generic one.

**Wired in this pass:**
| Event | Where |
|---|---|
| `validation.started` | `POST /api/v1/validations` |
| `validation.terminated` | `POST /api/v1/validations/<id>/cancel` |
| `report.generated` | PDF download |
| `meeting.created` | successful booking |
| `meeting.cancelled` | cancellation (includes the reason) |
| `role.created` / `role.updated` / `role.deleted` | Role Management UI |
| `permission.updated` | role permission set changed |
| `user.role_assigned` | user↔role assignment changed |
| `user.activated` | account activation |

**Not wired (flagged, not silently skipped):** `meeting.edited` and
`schedule.modified` from your original list have no corresponding endpoint
yet in the app (there's no "edit a booking" or "edit a slot template" flow
today — bookings are create/cancel only, and slot/tool config changes go
through Django's built-in `/admin/`, which has its own separate history
log). Say the word if you want either of those built out.

Viewing the trail: Django admin's `AuditLog` list (already registered)
now shows/filters/searches the new `action`/`module` fields. A dedicated
in-app audit viewer (outside Django admin) wasn't built — flag if you want
one; it's a straightforward addition on top of this schema.

---

## 6. Exact files — 22 new, 9 modified (verified by diff against v12)

### New
```
apps/rbac/__init__.py
apps/rbac/apps.py
apps/rbac/models.py
apps/rbac/permissions.py
apps/rbac/decorators.py
apps/rbac/context_processors.py
apps/rbac/views.py
apps/rbac/urls.py
apps/rbac/management/__init__.py
apps/rbac/management/commands/__init__.py
apps/rbac/management/commands/seed_rbac.py
apps/rbac/migrations/__init__.py
apps/rbac/migrations/0001_initial.py
apps/audit/log.py
apps/audit/migrations/0002_auditlog_action_auditlog_detail_auditlog_module_and_more.py
apps/accounts/migrations/0002_user_roles_alter_user_role.py
apps/scheduler/migrations/0005_meeting_cancellation_reason_meeting_cancelled_at_and_more.py
templates/403.html
templates/rbac/role_list.html
templates/rbac/role_form.html
templates/rbac/user_roles.html
```

### Modified
```
apps/accounts/models.py       — User.roles M2M, has_perm_code(), is_admin_role/can_validate now permission-driven
apps/accounts/views.py        — activate_user/dashboard/dashboard_export gated + audited
apps/audit/models.py          — +action/+module/+detail fields
apps/audit/admin.py           — list_display/filter/search updated
apps/scheduler/models.py      — Meeting +cancelled_by/+cancelled_at/+cancellation_reason
apps/scheduler/views.py       — every view permission-gated; cancel requires mandatory reason + logs audit
apps/validation/views.py      — every view permission-gated; start/cancel log audit; report_pdf logs audit
config/settings.py            — apps.rbac in INSTALLED_APPS + context processor registered
config/urls.py                — apps.rbac.urls included
templates/base.html           — nav pills gated per-module by perms_set; new "Roles" pill; Admin pill now gated on is_staff
templates/dashboard.html      — Cancelled By/Reason columns, cancellation modal, action buttons gated
templates/verify.html         — Run Verification form gated by verification.execute (view-only banner otherwise)
```

---

## 7. Deployment steps

```powershell
# 1. Stop the server, back up your working copy as usual.
# 2. Copy the 22 new files + 9 modified files into identical paths.

.venv\Scripts\Activate.ps1

# 3. Migrate — 4 new migrations across 3 apps + the new rbac app
python manage.py migrate
#   expect: rbac.0001_initial, accounts.0002_..., audit.0002_...,
#           scheduler.0005_... all applying OK

# 4. Seed permissions + starter roles + migrate existing users onto them
python manage.py seed_rbac
#   idempotent — safe to re-run any time (e.g. after adding a new
#   permission to PERMISSION_CATALOGUE later)

# 5. Restart
python manage.py runserver
```

### Verify in 5 minutes
1. Log in as an existing user who was `SCRUM_MASTER` before — nothing
   should look different; they should land on `Scrum Master` automatically.
2. Log in as your superuser → **Roles** pill appears in the navbar →
   `/manage/roles/` shows the 4 starter roles.
3. Create a test role with only `dashboard.view` + `reports.view` checked
   → assign it to a test user via **Assign to Users** → log in as that
   user → confirm they see the dashboard but the Verify/Scheduler nav
   pills are gone (no `*.view` permission) and a direct `curl`/browser hit
   to `/verify/` returns the 403 page.
4. As a user **with** `schedules.cancel`, cancel a real booking → confirm
   the modal blocks submission with an empty reason → fill a reason →
   confirm the dashboard row now shows Cancelled By/Reason instead of the
   button, and the `[EDCS-CANCEL]` PA email still goes out.
5. Django admin → Audit logs → filter by `action` — see the new semantic
   entries alongside the generic HTTP-level ones.

No changes to Power Automate are needed for this feature — the cancel
trigger email format is unchanged.
