# Integration snippets (drift-prone files)

These three files differ between your GitHub `main` (baseline) and your working
copy (v1–v3 already applied), so they are delivered as **insert snippets**, not
full-file overwrites. Paste each snippet into your working copy.

---

## A. `apps/adminconfig/models.py` — register the new config models

Add ONE line at the very bottom of the file:

```python
from .followup_models import HandoverFollowupConfig, EscalationPolicy  # noqa: E402,F401
```

## B. `apps/adminconfig/admin.py` — register the new admin pages

Add ONE line at the very bottom of the file:

```python
from . import followup_admin  # noqa: F401  (registers HandoverFollowupConfig + EscalationPolicy admin)
```

---

## C. `apps/scheduler/models.py` — Meeting GO-live fields

Paste the block from `apps/scheduler/_MEETING_FIELDS_SNIPPET.py` inside
`class Meeting` (e.g. right after the `cancellation_reason` field). `settings`
and `models` are already imported at the top of that file.

---

## D. `apps/scheduler/urls.py` — wire the GO-live action

Add the import near the top (next to `from . import views`):

```python
from . import golive_views
```

Add this path inside `urlpatterns` (next to the existing cancel/reschedule paths):

```python
    path("meetings/<uuid:meeting_id>/go-live/", golive_views.mark_go_live, name="mark-go-live"),
```

---

## E. `apps/scheduler/views.py` — send participant notices on cancel & reschedule

### E1. Cancellation notice
In `cancel_booking`, AFTER the meeting is saved as CANCELLED and the audit line
is logged (right before the final `return redirect("/")`), add:

```python
    # Notify all participants that the handover was cancelled.
    try:
        from apps.notifications.handover_emails import meeting_cancelled_notice
        meeting_cancelled_notice(m, reason=reason, actor=request.user)
    except Exception:
        pass
```

### E2. Reschedule notice
In `reschedule_booking` (your v1 view: it creates the NEW meeting first, then
cancels the OLD one). AFTER the new meeting's PA request succeeds and the old
meeting has been marked cancelled, add — using whatever your local variable
names are for the old and new Meeting objects (commonly `old`/`m` and
`new_meeting`/`new_m`):

```python
    # Notify all participants of the reschedule (old -> new).
    try:
        from apps.notifications.handover_emails import meeting_rescheduled_notice
        meeting_rescheduled_notice(old_meeting, new_meeting, actor=request.user)
    except Exception:
        pass
```

> If your reschedule view reuses `cancel_booking` internally to drop the old
> slot, make sure the cancellation email there does NOT also fire for a
> reschedule. Simplest guard: pass a flag or send the reschedule notice only,
> and skip E1 when the cancel is part of a reschedule. See APPLY_GUIDE "Avoiding
> double emails".

---

## F. `templates/dashboard.html` — "Mark GO-live done" button

In the **Handover Bookings** table, the action cell currently shows the Cancel
(and Reschedule) buttons for `scheduled` rows. Add a GO-live button for
**completed** rows that are not yet marked GO-live.

Find the action `<td>` in the bookings row loop and add this branch:

```django
{% if b.display_status == "completed" and not b.m.go_live_done and "schedules.edit" in perms_set %}
  <form method="post" action="/meetings/{{ b.m.id }}/go-live/" style="display:inline;margin:0">
    {% csrf_token %}
    <button type="submit" class="btn btn-success btn-sm"
            onclick="return confirm('Mark this handover as moved to GO live? Follow-up reminders will stop.');">
      <i class="bi bi-rocket-takeoff"></i> Mark GO-live
    </button>
  </form>
{% elif b.m.go_live_done %}
  <span class="badge" style="background:#d6ead7;color:#1e6b2e">
    <i class="bi bi-check-circle-fill"></i> GO-live
  </span>
{% endif %}
```

Optional: if you added a `go_live_done` sort/status, you can also surface it as
a column. Not required for the feature to work.
