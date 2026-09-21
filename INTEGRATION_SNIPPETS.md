# EDCS-Gate — Integration Snippets (Requirements Batch 2)

All edits are **additive** and anchored to original code that exists in both
GitHub `main` and your running copy. Search for the quoted anchor text, then
paste as directed. Nothing existing is removed unless explicitly stated.

Requirements covered:
1. ERIDOC folder-path field on Verify (admin-configurable required/optional per tool)
2. JIRA Type (Story / Enhancement) + Enhancement JIRA, admin-configurable
3. Nomenclature & quality guidelines file (see `docs/`)
4. Reject junk cancellation/reschedule reasons (see `apps/scheduler/reason_validation.py`)
5. Scrum Master column + search + logged-in scrum-master scoping

---

## A. `apps/adminconfig/models.py` — new JiraType model + ToolConfig field

### A1. Add the `JiraType` model (Req 2, admin-configurable)

Paste this new class near the top, right AFTER the `AutomationType` class ends
(after its `get_notification_email_list` method) and BEFORE `class ToolConfig`:

```python
class JiraType(models.Model):
    """Configurable JIRA work-item type shown on the Verify page.

    Seed rows: 'Story' (requires_parent=False) and
    'Enhancement' (requires_parent=True). When requires_parent is True the
    Verify page shows a separate 'Enhancement JIRA ID' field and treats the
    existing JIRA field as the 'Parent JIRA'.
    """
    key = models.SlugField(max_length=32, unique=True,
                           help_text="Short identifier, e.g. STORY or ENHANCEMENT")
    display_name = models.CharField(max_length=64)
    requires_parent = models.BooleanField(
        default=False,
        help_text=("Tick for Enhancement-style types: the Verify page will show "
                   "a separate 'Enhancement JIRA ID' field and treat the main "
                   "JIRA field as the Parent (Story) JIRA."),
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "key"]
        verbose_name = "JIRA Type"
        verbose_name_plural = "JIRA Types"

    def __str__(self):
        tag = "needs parent" if self.requires_parent else "standalone"
        return f"{self.display_name} ({tag})"
```

### A2. Add the ERIDOC-path mode field to `ToolConfig` (Req 1, admin-configurable)

Find this block inside `class ToolConfig`:

```python
    scanners = models.JSONField(default=list,
        help_text='List of scanner keys, e.g. ["ERIDOC", "BITBUCKET"]')
```

Add IMMEDIATELY AFTER it:

```python
    eridoc_path_mode = models.CharField(
        max_length=10,
        choices=[("REQUIRED", "Required"), ("OPTIONAL", "Optional")],
        default="OPTIONAL",
        help_text=("Only applies when 'ERIDOC' is in this tool's scanners. "
                   "REQUIRED = user must enter an ERIDOC folder path on Verify. "
                   "OPTIONAL = field shown but may be left blank, in which case "
                   "the scanner falls back to the JIRA-based lookup."),
    )
```

---

## B. `apps/adminconfig/admin.py` — register JiraType + expose the new field

Find:

```python
@admin.register(models.ToolConfig)
class ToolConfigAdmin(admin.ModelAdmin):
    list_display  = ("key", "display_name", "requires_repo_url",
                     "scanners", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
```

Replace the `list_display` line's tail and add fields so it reads:

```python
@admin.register(models.ToolConfig)
class ToolConfigAdmin(admin.ModelAdmin):
    list_display  = ("key", "display_name", "requires_repo_url",
                     "scanners", "eridoc_path_mode", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")


@admin.register(models.JiraType)
class JiraTypeAdmin(admin.ModelAdmin):
    list_display  = ("key", "display_name", "requires_parent",
                     "is_active", "sort_order")
    list_editable = ("requires_parent", "is_active", "sort_order")
```

---

## C. `apps/validation/models.py` — new fields on ValidationRun

Find:

```python
    jira_id = models.CharField(max_length=32, db_index=True)
    repo_url = models.URLField(max_length=512, blank=True, default="")
```

Add IMMEDIATELY AFTER those two lines:

```python
    # ── Req 1: explicit ERIDOC folder path (optional; falls back to JIRA lookup)
    eridoc_path = models.CharField(max_length=512, blank=True, default="")
    # ── Req 2: JIRA work-item type + parent (Story vs Enhancement)
    jira_type = models.ForeignKey(
        "adminconfig.JiraType", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="validation_runs")
    parent_jira_id = models.CharField(max_length=32, blank=True, default="")
```

---

## D. `apps/validation/services.py` — accept & validate the new inputs

### D1. Update the `start_run` signature

Find:

```python
def start_run(user, tool_key: str, jira_id: str, repo_url: str = "",
              customer_name: str = "", automation_name: str = "",
              automation_type_key: str = "") -> ValidationRun:
```

Replace with:

```python
def start_run(user, tool_key: str, jira_id: str, repo_url: str = "",
              customer_name: str = "", automation_name: str = "",
              automation_type_key: str = "",
              jira_type_key: str = "", parent_jira_id: str = "",
              eridoc_path: str = "") -> ValidationRun:
```

### D2. Add import for JiraType

Find:

```python
from apps.adminconfig.models import ToolConfig, AutomationType
```

Replace with:

```python
from apps.adminconfig.models import ToolConfig, AutomationType, JiraType
```

### D3. Validate JIRA type + parent/enhancement (Req 2)

Find the JIRA ID validation block:

```python
    # ── Validate JIRA ID ─────────────────────────────────────────────────
    jira_id = jira_id.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", jira_id):
        raise ValidationError("JIRA ID must look like PROJ-1234.")
```

Add IMMEDIATELY AFTER it:

```python
    # ── Validate JIRA type + parent/enhancement (Req 2) ───────────────────
    jira_type = None
    parent_jira_id = (parent_jira_id or "").strip().upper()
    if jira_type_key:
        jira_type = JiraType.objects.filter(
            key=jira_type_key, is_active=True).first()
        if jira_type is None:
            raise ValidationError("Selected JIRA type is not valid.")
    if jira_type and jira_type.requires_parent:
        # 'jira_id' already holds the Enhancement JIRA (mapped by the form).
        # 'parent_jira_id' must hold the Parent Story JIRA.
        if not parent_jira_id:
            raise ValidationError("Parent JIRA is required for an Enhancement.")
        if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", parent_jira_id):
            raise ValidationError("Parent JIRA must look like PROJ-1234.")
        if parent_jira_id == jira_id:
            raise ValidationError(
                "Parent JIRA and Enhancement JIRA cannot be the same.")
    else:
        parent_jira_id = ""   # Story (or no type): no parent
```

### D4. Validate ERIDOC path per tool mode (Req 1)

Find the repo-url validation block:

```python
    # ── Validate repo URL ─────────────────────────────────────────────────
    if tool.requires_repo_url:
```

Add IMMEDIATELY BEFORE that block:

```python
    # ── Validate ERIDOC folder path (Req 1) ───────────────────────────────
    eridoc_path = (eridoc_path or "").strip()
    tool_scanners = [s.upper() for s in (tool.scanners or [])]
    if "ERIDOC" in tool_scanners:
        mode = getattr(tool, "eridoc_path_mode", "OPTIONAL")
        if mode == "REQUIRED" and not eridoc_path:
            raise ValidationError(
                "This tool requires an ERIDOC folder path/link.")
        if len(eridoc_path) > 512:
            raise ValidationError("ERIDOC folder path is too long (max 512).")
    else:
        eridoc_path = ""   # not applicable for tools without the ERIDOC scanner
```

### D5. Persist the new fields on create

Find:

```python
    run = ValidationRun.objects.create(
        tool=tool,
        jira_id=jira_id,
        repo_url=repo_url,
        requested_by=user,
        customer_name=customer_name,
        automation_name=automation_name,
        automation_type=automation_type,      # ← new FK
        status=ValidationRun.Status.RUNNING,
    )
```

Replace with:

```python
    run = ValidationRun.objects.create(
        tool=tool,
        jira_id=jira_id,
        repo_url=repo_url,
        requested_by=user,
        customer_name=customer_name,
        automation_name=automation_name,
        automation_type=automation_type,
        jira_type=jira_type,                   # ← Req 2
        parent_jira_id=parent_jira_id,         # ← Req 2
        eridoc_path=eridoc_path,               # ← Req 1
        status=ValidationRun.Status.RUNNING,
    )
```

---

## E. `apps/validation/views.py` — pass the new fields from the request

Find:

```python
        run = start_run(
            request.user,
            data.get("tool_key", ""),
            data.get("jira_id", ""),
            data.get("repo_url", ""),
            data.get("customer_name", ""),
            data.get("automation_name", ""),
            data.get("automation_type_key", ""),   # ← new field
        )
```

Replace with:

```python
        run = start_run(
            request.user,
            data.get("tool_key", ""),
            data.get("jira_id", ""),
            data.get("repo_url", ""),
            data.get("customer_name", ""),
            data.get("automation_name", ""),
            data.get("automation_type_key", ""),
            data.get("jira_type_key", ""),          # ← Req 2
            data.get("parent_jira_id", ""),         # ← Req 2
            data.get("eridoc_path", ""),            # ← Req 1
        )
```

---

## F. `apps/scanners/eridoc_adapter.py` — use the ERIDOC path (Req 1)

### F1. Update the `run` entry point

Find:

```python
def run(jira_id: str) -> ScanResult:
    return _run_demo(jira_id) if dj.DEMO_MODE else _run_real(jira_id)
```

Replace with:

```python
def run(jira_id: str, eridoc_path: str = "") -> ScanResult:
    # When an explicit ERIDOC folder path/link is supplied it takes precedence
    # over the JIRA-based lookup; blank falls back to the original behaviour.
    return (_run_demo(jira_id) if dj.DEMO_MODE
            else _run_real(jira_id, eridoc_path))
```

### F2. Update `_run_real` to use the path

Find:

```python
def _run_real(jira_id: str) -> ScanResult:
    from edcs.config import get_settings
    from edcs.document_scanner.scanner import DocumentScanner
    from edcs.models import Severity
    from edcs.exceptions import EridocError
    s = get_settings()
    scanner = DocumentScanner(s)
    try:
        findings, docs, score, caps = scanner.scan(jira_id)
```

Replace the last two lines (the `scanner = ...` and `findings ... = scanner.scan(jira_id)`) so the block reads:

```python
def _run_real(jira_id: str, eridoc_path: str = "") -> ScanResult:
    from edcs.config import get_settings
    from edcs.document_scanner.scanner import DocumentScanner
    from edcs.models import Severity
    from edcs.exceptions import EridocError
    s = get_settings()
    scanner = DocumentScanner(s)
    # Prefer an explicit folder path/link when provided; otherwise scan by JIRA.
    scan_target = eridoc_path.strip() if eridoc_path and eridoc_path.strip() else jira_id
    try:
        findings, docs, score, caps = scanner.scan(scan_target)
```

> NOTE: If your vendored `DocumentScanner.scan()` takes the folder path under a
> different keyword (e.g. `scan(jira_id, folder=...)`), adjust this one call
> accordingly. The adapter now has `eridoc_path` available to pass however your
> engine expects.

---

## G. `apps/validation/tasks.py` — thread the path to the adapter (Req 1)

Find:

```python
        adapter = ADAPTERS[scanner]
        scan = (adapter.run(run.jira_id) if scanner == "ERIDOC"
                else adapter.run(run.repo_url))
```

Replace with:

```python
        adapter = ADAPTERS[scanner]
        scan = (adapter.run(run.jira_id, run.eridoc_path) if scanner == "ERIDOC"
                else adapter.run(run.repo_url))
```

---

## H. `apps/scheduler/views.py` — reject junk cancellation reasons (Req 4)

Find:

```python
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "A cancellation reason is required.")
        return redirect("/")
    if len(reason) > 1000:
        reason = reason[:1000]
```

Replace with:

```python
    from .reason_validation import validate_reason
    ok, cleaned = validate_reason(request.POST.get("reason"))
    if not ok:
        messages.error(request, cleaned)   # cleaned holds the error message
        return redirect("/")
    reason = cleaned
```

> If your running copy also has a `reschedule_booking` view that captures a
> reason, apply the same three-line `validate_reason(...)` guard there.

---

## I. `apps/scheduler/services.py` — dashboard rows + Excel columns (Req 2 & 5)

### I1. Surface scrum master, JIRA type, parent/enhancement in each row

Find:

```python
        vr = m.validation_run
        # Automation Type display name (e.g. "Execution") — new field
        at = vr.automation_type if vr else None
        out.append({
            "m": m,
            "display_status": disp,
            "jira_id": vr.jira_id if vr else "",
            "customer_name": vr.customer_name if vr else "",
            "automation_name": vr.automation_name if vr else "",
            # ↓ NEW fields
            "automation_type_display": at.display_name if at else "—",
            "automation_type_key": at.key if at else "",
            "requires_scheduling": at.requires_scheduling if at else True,
        })
```

Replace with:

```python
        vr = m.validation_run
        at = vr.automation_type if vr else None
        # Scrum master(s) recorded on the meeting (Req 5)
        sm_emails = [a.email for a in m.attendees.all()
                     if a.type == "SCRUM_MASTER"]
        out.append({
            "m": m,
            "display_status": disp,
            "jira_id": vr.jira_id if vr else "",
            "customer_name": vr.customer_name if vr else "",
            "automation_name": vr.automation_name if vr else "",
            "automation_type_display": at.display_name if at else "—",
            "automation_type_key": at.key if at else "",
            "requires_scheduling": at.requires_scheduling if at else True,
            # ↓ Req 2
            "jira_type_display": (vr.jira_type.display_name
                                  if vr and vr.jira_type else "—"),
            "parent_jira_id": (vr.parent_jira_id if vr else "") or "",
            # ↓ Req 5 — resolved names computed in the view/template
            "scrum_master_emails": sm_emails,
        })
```

### I2. Extend the search filter to include scrum-master email (Req 5)

Find:

```python
    if q:
        rows = rows.filter(
            Q(organizer__username__icontains=q) | Q(tool_key__icontains=q) |
            Q(subject__icontains=q) | Q(validation_run__jira_id__icontains=q) |
            Q(attendees__email__icontains=q)
        ).distinct()
```

Replace with (adds parent-JIRA search; scrum-master email is already covered by
`attendees__email`, but we make the intent explicit and add parent JIRA):

```python
    if q:
        rows = rows.filter(
            Q(organizer__username__icontains=q) | Q(tool_key__icontains=q) |
            Q(subject__icontains=q) | Q(validation_run__jira_id__icontains=q) |
            Q(validation_run__parent_jira_id__icontains=q) |
            Q(attendees__email__icontains=q)
        ).distinct()
```

### I3. Add a `scrum_master`, `jira_type`, `parent` filter arg (Req 2 & 5)

Find the function signature:

```python
def filtered_bookings(q="", tool="", status="", date_from="", date_to=""):
```

Replace with:

```python
def filtered_bookings(q="", tool="", status="", date_from="", date_to="",
                      jira_type="", scrum_master_email=""):
```

Then find:

```python
    if tool:
        rows = rows.filter(tool_key=tool)
```

Add IMMEDIATELY AFTER it:

```python
    if jira_type:
        rows = rows.filter(validation_run__jira_type__key=jira_type)
    if scrum_master_email:
        rows = rows.filter(
            attendees__type="SCRUM_MASTER",
            attendees__email__iexact=scrum_master_email,
        ).distinct()
```

### I4. Excel — add JIRA Type, Parent JIRA, Scrum Master columns (Sheet 1)

Find:

```python
    HEADERS_S1 = [
        "Username", "Tool", "Automation Type", "Customer",
        "Date", "Slot", "JIRA ID", "Automation Name",
        "Developers", "Scrum Masters", "CC",
        "Status", "Created",
    ]
```

Replace with:

```python
    HEADERS_S1 = [
        "Username", "Tool", "Automation Type", "JIRA Type", "Customer",
        "Date", "Slot", "JIRA ID", "Parent JIRA", "Automation Name",
        "Developers", "Scrum Masters", "CC",
        "Status", "Created",
    ]
```

Find the row-append for Sheet 1:

```python
        ws1.append([
            m.organizer.username,
            m.tool_key,
            at_disp,                                                     # ← NEW
            m.validation_run.customer_name if m.validation_run else "",
            str(m.booking_date or m.start_at.date()),
            m.slot.label if m.slot else "",
            r["jira_id"],
            r["automation_name"],
            pick("DEVELOPER"),
            pick("SCRUM_MASTER"),
            pick("CC"),
            disp_st,
            m.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
```

Replace with:

```python
        ws1.append([
            m.organizer.username,
            m.tool_key,
            at_disp,
            r.get("jira_type_display", "—"),                            # ← Req 2
            m.validation_run.customer_name if m.validation_run else "",
            str(m.booking_date or m.start_at.date()),
            m.slot.label if m.slot else "",
            r["jira_id"],
            r.get("parent_jira_id", ""),                                # ← Req 2
            r["automation_name"],
            pick("DEVELOPER"),
            pick("SCRUM_MASTER"),                                        # ← Req 5 (already present)
            pick("CC"),
            disp_st,
            m.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
```

> Because two columns were inserted, the colour-coding column indices shift.
> Find this line just below the append:
>
> ```python
>         cell.alignment = _center() if col_idx in (1, 2, 3, 5, 6, 12, 13) else _left()
> ```
> and this pair:
> ```python
>             if col_idx == 3:
>                 cell.fill = _fill(_type_colour(at_key))
>             elif col_idx == 12:
>                 cell.fill = _fill(_status_colour(disp_st))
> ```
> Update the indices: Automation Type is still col **3**; Status is now col
> **14**; Created is col **15**. So change `(1, 2, 3, 5, 6, 12, 13)` →
> `(1, 2, 3, 4, 6, 7, 14, 15)` and change `elif col_idx == 12:` →
> `elif col_idx == 14:`.

### I5. Excel — add Parent JIRA to Sheet 2 (No Meeting Needed) for consistency

Find:

```python
    HEADERS_S2 = [
        "Username", "Tool", "Automation Type", "Customer",
        "JIRA ID", "Automation Name",
        "Status", "Remarks", "Scan Date",
    ]
```

Replace with:

```python
    HEADERS_S2 = [
        "Username", "Tool", "Automation Type", "JIRA Type", "Customer",
        "JIRA ID", "Parent JIRA", "Automation Name",
        "Status", "Remarks", "Scan Date",
    ]
```

Find the Sheet-2 append:

```python
        ws2.append([
            vr.requested_by.username if vr.requested_by else "",
            vr.tool.key if vr.tool else "",
            at_disp,
            getattr(vr, "customer_name", ""),
            vr.jira_id,
            getattr(vr, "automation_name", ""),
            vr.status,
            remark,
            vr.started_at.strftime("%Y-%m-%d %H:%M") if vr.started_at else "",
        ])
```

Replace with:

```python
        ws2.append([
            vr.requested_by.username if vr.requested_by else "",
            vr.tool.key if vr.tool else "",
            at_disp,
            vr.jira_type.display_name if vr.jira_type else "—",         # ← Req 2
            getattr(vr, "customer_name", ""),
            vr.jira_id,
            getattr(vr, "parent_jira_id", "") or "",                    # ← Req 2
            getattr(vr, "automation_name", ""),
            vr.status,
            remark,
            vr.started_at.strftime("%Y-%m-%d %H:%M") if vr.started_at else "",
        ])
```

> Sheet-2 colour indices also shift by the two inserted columns. Find:
> ```python
>             cell.alignment = _center() if col_idx in (1, 2, 3, 7, 9) else _left()
> ```
> and:
> ```python
>             if col_idx == 3:
>                 cell.fill = _fill(_type_colour(at_key))
>             elif col_idx == 7:
> ```
> Status is now col **9**. Change `(1, 2, 3, 7, 9)` → `(1, 2, 3, 4, 9, 11)` and
> change `elif col_idx == 7:` → `elif col_idx == 9:`.

---

## J. `templates/verify.html` — JIRA Type + Enhancement JIRA + ERIDOC path (Req 1 & 2)

### J1. Add the JIRA Type select + Enhancement JIRA field

Find the JIRA ID field block:

```django
        <!-- JIRA ID -->
        <div class="field-group">
          <label for="jira_id">JIRA ID</label>
          <input type="text" id="jira_id" placeholder="e.g. PROJ-1234" required
                 {% if "verification.execute" not in perms_set %}disabled{% endif %}>
        </div>
```

Replace the whole block with:

```django
        <!-- JIRA Type (Req 2) -->
        <div class="field-group">
          <label for="jira_type">JIRA Type</label>
          <select id="jira_type" {% if "verification.execute" not in perms_set %}disabled{% endif %}>
            <option value="" selected>— Select type —</option>
            {% for jt in jira_types %}
              <option value="{{ jt.key }}" data-requires-parent="{{ jt.requires_parent|yesno:'1,0' }}">
                {{ jt.display_name }}
              </option>
            {% endfor %}
          </select>
        </div>

        <!-- JIRA ID / Parent JIRA (label switches with JIRA type) -->
        <div class="field-group">
          <label for="jira_id" id="jira_id_label">JIRA ID</label>
          <input type="text" id="jira_id" placeholder="e.g. PROJ-1234" required
                 {% if "verification.execute" not in perms_set %}disabled{% endif %}>
        </div>

        <!-- Enhancement JIRA ID (only for Enhancement types) -->
        <div class="field-group" id="enh-group" style="display:none">
          <label for="enhancement_jira">Enhancement JIRA ID</label>
          <input type="text" id="enhancement_jira" placeholder="e.g. PROJ-1299"
                 {% if "verification.execute" not in perms_set %}disabled{% endif %}>
        </div>
```

### J2. Add the ERIDOC folder-path field (Req 1)

Find the Bitbucket link block:

```django
        <!-- Bitbucket Link (conditional) -->
        <div class="field-group" id="repo-group" style="display:none">
          <label for="bitbucket_link">Bitbucket Link</label>
          <input type="text" id="bitbucket_link" placeholder="https://bitbucket.../repo"
                 {% if "verification.execute" not in perms_set %}disabled{% endif %}>
        </div>
```

Add IMMEDIATELY BEFORE it:

```django
        <!-- ERIDOC folder path/link (conditional — tools with the ERIDOC scanner) -->
        <div class="field-group" id="eridoc-group" style="display:none">
          <label for="eridoc_path">ERIDOC Folder Path / Link <span id="eridoc-req" style="color:var(--danger);display:none">*</span></label>
          <input type="text" id="eridoc_path" placeholder="e.g. /ERIDOC/ACE-5821 or https://eridoc.../folder"
                 {% if "verification.execute" not in perms_set %}disabled{% endif %}>
          <div class="field-hint" id="eridoc-hint" style="font-size:.78rem"></div>
        </div>
```

### J3. Update the tool `<option>` to carry ERIDOC metadata

Find:

```django
              <option value="{{ t.key }}" data-repo="{{ t.requires_repo_url|yesno:'1,0' }}">{{ t.display_name }}</option>
```

Replace with:

```django
              <option value="{{ t.key }}"
                      data-repo="{{ t.requires_repo_url|yesno:'1,0' }}"
                      data-eridoc="{% if 'ERIDOC' in t.scanners %}1{% else %}0{% endif %}"
                      data-eridoc-required="{% if t.eridoc_path_mode == 'REQUIRED' %}1{% else %}0{% endif %}">{{ t.display_name }}</option>
```

### J4. JavaScript — wire the new fields

Find this JS var block near the top of the script:

```javascript
  const jira        = document.getElementById('jira_id');
```

Add AFTER it:

```javascript
  const jiraLabel   = document.getElementById('jira_id_label');
  const jiraTypeSel = document.getElementById('jira_type');
  const enhGroup    = document.getElementById('enh-group');
  const enhJira     = document.getElementById('enhancement_jira');
  const eridocGroup = document.getElementById('eridoc-group');
  const eridocInput = document.getElementById('eridoc_path');
  const eridocReq   = document.getElementById('eridoc-req');
  const eridocHint  = document.getElementById('eridoc-hint');
  let needsEridoc      = false;
  let eridocMandatory  = false;
```

Find the `toolSel.onchange` handler:

```javascript
  toolSel.onchange = () => {
    needsRepo = toolSel.selectedOptions[0].dataset.repo === '1';
    repoGroup.style.display = needsRepo ? 'block' : 'none';
    check();
  };
```

Replace with:

```javascript
  toolSel.onchange = () => {
    const opt = toolSel.selectedOptions[0];
    needsRepo = opt.dataset.repo === '1';
    repoGroup.style.display = needsRepo ? 'block' : 'none';
    // ERIDOC path field (Req 1)
    needsEridoc     = opt.dataset.eridoc === '1';
    eridocMandatory = needsEridoc && opt.dataset.eridocRequired === '1';
    eridocGroup.style.display = needsEridoc ? 'block' : 'none';
    eridocReq.style.display   = eridocMandatory ? 'inline' : 'none';
    eridocHint.textContent    = needsEridoc
      ? (eridocMandatory
          ? 'Required for this tool.'
          : 'Optional — leave blank to scan by JIRA ID (default behaviour).')
      : '';
    check();
  };
```

Find the JIRA-type change wiring — add this NEW handler right after the
`atSel.onchange` line (`atSel.onchange = () => { updateTypeHint(); check(); };`):

```javascript
  jiraTypeSel.onchange = () => {
    const opt = jiraTypeSel.selectedOptions[0];
    const needsParent = opt && opt.dataset.requiresParent === '1';
    enhGroup.style.display = needsParent ? 'block' : 'none';
    jiraLabel.textContent  = needsParent ? 'Parent JIRA' : 'JIRA ID';
    jira.placeholder       = needsParent ? 'Parent Story, e.g. PROJ-1234'
                                          : 'e.g. PROJ-1234';
    check();
  };
```

Find the `check()` function body and its `okRepo` line:

```javascript
    const okRepo       = !needsRepo || repo.value.trim().length > 10;
    btn.disabled = !(toolSel.value && okCustomer && okAutomation && okType && okJira && okRepo);
```

Replace with:

```javascript
    const okRepo       = !needsRepo || repo.value.trim().length > 10;
    const jiraTypeOpt  = jiraTypeSel.selectedOptions[0];
    const needsParent  = jiraTypeOpt && jiraTypeOpt.dataset.requiresParent === '1';
    const okEnh        = !needsParent ||
                         /^[A-Za-z][A-Za-z0-9]+-\d+$/.test(enhJira.value.trim());
    const okEridoc     = !eridocMandatory || eridocInput.value.trim().length > 0;
    btn.disabled = !(toolSel.value && okCustomer && okAutomation && okType
                     && okJira && okRepo && okEnh && okEridoc);
```

Add these input listeners near the other `.oninput` bindings:

```javascript
  enhJira.oninput     = check;
  eridocInput.oninput = check;
```

Find the request body builder in `btn.onclick`:

```javascript
    const body = {
      tool_key:           toolSel.value,
      jira_id:            jira.value.trim(),
      customer_name:      customer.value.trim(),
      automation_name:    automation.value.trim(),
      automation_type_key: atSel.value,
      repo_url:           needsRepo ? repo.value.trim() : '',
    };
```

Replace with:

```javascript
    const jiraTypeOpt = jiraTypeSel.selectedOptions[0];
    const needsParent = jiraTypeOpt && jiraTypeOpt.dataset.requiresParent === '1';
    // For an Enhancement, the primary JIRA is the Enhancement id and the main
    // field carries the Parent JIRA; for a Story the main field is the JIRA id.
    const body = {
      tool_key:            toolSel.value,
      jira_id:             needsParent ? enhJira.value.trim() : jira.value.trim(),
      parent_jira_id:      needsParent ? jira.value.trim() : '',
      jira_type_key:       jiraTypeSel.value,
      customer_name:       customer.value.trim(),
      automation_name:     automation.value.trim(),
      automation_type_key: atSel.value,
      repo_url:            needsRepo ? repo.value.trim() : '',
      eridoc_path:         needsEridoc ? eridocInput.value.trim() : '',
    };
```

> The Verify view already passes `tools` and `automation_types`. Add `jira_types`
> in section L below.

---

## K. `templates/dashboard.html` — Scrum Master column, JIRA Type, filter, junk-reason JS (Req 2, 4, 5)

### K1. Add JIRA Type filter + scrum-master search hint

Find the Tool filter block:

```django
          <div class="field-group" style="margin:0">
            <label>Tool</label>
            <select name="tool">
              <option value="">All tools</option>
              {% for t in tools %}
                <option value="{{ t.key }}" {% if tool_filter == t.key %}selected{% endif %}>{{ t.display_name }}</option>
              {% endfor %}
            </select>
          </div>
```

Add IMMEDIATELY AFTER it:

```django
          <div class="field-group" style="margin:0">
            <label>JIRA Type</label>
            <select name="jira_type">
              <option value="">All types</option>
              {% for jt in jira_types %}
                <option value="{{ jt.key }}" {% if jira_type_filter == jt.key %}selected{% endif %}>{{ jt.display_name }}</option>
              {% endfor %}
            </select>
          </div>
```

Also update the Search placeholder to mention scrum master. Find:

```django
          <input type="text" name="q" placeholder="Username, tool, or JIRA ID" value="{{ query }}">
```

Replace with:

```django
          <input type="text" name="q" placeholder="Username, tool, JIRA ID, parent JIRA, or scrum master email" value="{{ query }}">
```

### K2. Scrum-master scoping banner (Req 5)

Find the bookings table toolbar:

```django
<div class="table-toolbar">
  <h2 style="margin:0">Handover Bookings ({{ bookings|length }})</h2>
```

Add IMMEDIATELY AFTER the `<h2>` line (still inside the toolbar div), so a
logged-in scrum master sees a scoping note with a clear "view all" escape:

```django
  {% if sm_scoped %}
  <span class="badge" style="background:#e3f2fd;color:#0d47a1;margin-left:10px">
    <i class="bi bi-funnel-fill"></i> Showing handovers where you are the Scrum Master
    &nbsp;·&nbsp;<a href="/?all=1" style="color:#0d47a1;text-decoration:underline">view all</a>
  </span>
  {% endif %}
```

### K3. Add Scrum Master + JIRA Type columns to the bookings table header

Find:

```django
              <th>Customer</th>
              <th>Date</th>
```

Replace with:

```django
              <th>JIRA Type</th>
              <th>Customer</th>
              <th>Scrum Master</th>
              <th>Date</th>
```

### K4. Add the matching body cells

Find:

```django
              <td>{{ b.customer_name|default:"—" }}</td>
              <td>{{ b.m.booking_date|default:b.m.start_at|date:"Y-m-d" }}</td>
```

Replace with:

```django
              <td>{{ b.jira_type_display|default:"—" }}</td>
              <td>{{ b.customer_name|default:"—" }}</td>
              <td>
                {% if b.scrum_master_names %}
                  {% for nm in b.scrum_master_names %}
                    <span class="pill-person"><i class="bi bi-person-badge"></i> {{ nm }}</span>{% if not forloop.last %} {% endif %}
                  {% endfor %}
                {% else %}—{% endif %}
              </td>
              <td>{{ b.m.booking_date|default:b.m.start_at|date:"Y-m-d" }}</td>
```

> The two added `<th>`/`<td>` pairs keep the header and body column counts in
> sync. If your running copy shows a "Parent JIRA" need, you can also add
> `<td>{{ b.parent_jira_id|default:"—" }}</td>` under a `<th>Parent JIRA</th>`
> the same way.

### K5. Client-side junk-reason guard in the cancel modal (Req 4)

Find the cancel modal script:

```javascript
    function openCancelModal(meetingId, subject) {
      document.getElementById('cancelForm').action = '/meetings/' + meetingId + '/cancel/';
      document.getElementById('cancelSubjectLabel').textContent = subject;
      document.getElementById('cancelReason').value = '';
      new bootstrap.Modal(document.getElementById('cancelModal')).show();
    }
```

Add AFTER that function (still inside the `<script>` block):

```javascript
    (function () {
      const JUNK = new Set(['na','n/a','n.a','none','nil','nan','null','nn','no',
        'test','testing','abc','asdf','qwerty','xxx','xx','aaa','-','.','..','...',
        'dummy','sample','tbd','todo','ok','okay','done']);
      const form = document.getElementById('cancelForm');
      if (!form) return;
      form.addEventListener('submit', function (e) {
        const el = document.getElementById('cancelReason');
        const raw = (el.value || '').trim();
        const norm = raw.toLowerCase().replace(/\s+/g, ' ')
                        .replace(/^[\s.,\-_/\\|!?*#]+|[\s.,\-_/\\|!?*#]+$/g, '');
        const meaningful = raw.replace(/[\W_]+/g, '');
        let err = '';
        if (!raw) err = 'A cancellation reason is required.';
        else if (JUNK.has(norm)) err = 'Please provide a specific, meaningful reason (values like "NA"/"None"/"test" are not accepted).';
        else if (/^(.)\1*$/.test(norm)) err = 'Please provide a real reason, not repeated characters.';
        else if (meaningful.length < 8) err = 'The reason is too short — please describe why in at least 8 characters.';
        if (err) { e.preventDefault(); alert(err); el.focus(); }
      });
    })();
```

---

## L. `apps/accounts/views.py` — dashboard: scrum-master names, scoping, JIRA-type filter (Req 2 & 5)

### L1. Read the new query params + resolve scrum-master scoping

Find:

```python
    q             = request.GET.get("q", "").strip()
    tool_filter   = request.GET.get("tool", "")
    status_filter = request.GET.get("status", "")
    date_from     = request.GET.get("date_from", "")
    date_to       = request.GET.get("date_to", "")
```

Replace with:

```python
    q               = request.GET.get("q", "").strip()
    tool_filter     = request.GET.get("tool", "")
    status_filter   = request.GET.get("status", "")
    date_from       = request.GET.get("date_from", "")
    date_to         = request.GET.get("date_to", "")
    jira_type_filter = request.GET.get("jira_type", "")
    show_all        = request.GET.get("all", "") == "1"

    # Req 5 — if the logged-in user's email is used as a Scrum Master on any
    # meeting, default their dashboard to just those handovers (unless ?all=1).
    from apps.scheduler.models import MeetingAttendee
    user_email = (getattr(request.user, "email", "") or "").strip().lower()
    is_scrum_master = bool(user_email) and MeetingAttendee.objects.filter(
        type="SCRUM_MASTER", email__iexact=user_email).exists()
    sm_scope_email = user_email if (is_scrum_master and not show_all) else ""
```

### L2. Pass the new filters into `filtered_bookings`

Find:

```python
    rows  = filtered_bookings(q, tool_filter, status_filter, date_from, date_to)
```

Replace with:

```python
    rows  = filtered_bookings(q, tool_filter, status_filter, date_from, date_to,
                              jira_type=jira_type_filter,
                              scrum_master_email=sm_scope_email)
    # Resolve scrum-master display names (Req 5): username if a User has that
    # email, else the raw email address.
    from apps.accounts.models import User as _User
    _email_to_name = {}
    for r in rows:
        for em in r.get("scrum_master_emails", []):
            key = em.lower()
            if key not in _email_to_name:
                u = _User.objects.filter(email__iexact=em).first()
                _email_to_name[key] = (u.get_full_name() or u.username) if u else em
        r["scrum_master_names"] = [
            _email_to_name.get(em.lower(), em)
            for em in r.get("scrum_master_emails", [])
        ]
```

### L3. Add JIRA types + scoping flag to the template context

Find:

```python
    return render(request, "dashboard.html", {
        "nav":            "dashboard",
        "bookings":       rows,
        "stats":          stats,
        "tools":          ToolConfig.objects.filter(is_active=True),
        "query":          q,
        "tool_filter":    tool_filter,
        "status_filter":  status_filter,
        "date_from":      date_from,
        "date_to":        date_to,
        "pending_users":  pending_users,
        "no_meeting_runs": no_meeting_runs,   # ← new context variable
    })
```

Replace with:

```python
    from apps.adminconfig.models import JiraType
    return render(request, "dashboard.html", {
        "nav":            "dashboard",
        "bookings":       rows,
        "stats":          stats,
        "tools":          ToolConfig.objects.filter(is_active=True),
        "jira_types":     JiraType.objects.filter(is_active=True),
        "query":          q,
        "tool_filter":    tool_filter,
        "status_filter":  status_filter,
        "jira_type_filter": jira_type_filter,
        "date_from":      date_from,
        "date_to":        date_to,
        "pending_users":  pending_users,
        "no_meeting_runs": no_meeting_runs,
        "sm_scoped":      bool(sm_scope_email),
    })
```

### L4. Honour the JIRA-type filter in the Excel export too

Find:

```python
    rows = filtered_bookings(
        request.GET.get("q", "").strip(),
        request.GET.get("tool", ""),
        request.GET.get("status", ""),
        request.GET.get("date_from", ""),
        request.GET.get("date_to", ""),
    )
```

Replace with:

```python
    rows = filtered_bookings(
        request.GET.get("q", "").strip(),
        request.GET.get("tool", ""),
        request.GET.get("status", ""),
        request.GET.get("date_from", ""),
        request.GET.get("date_to", ""),
        jira_type=request.GET.get("jira_type", ""),
    )
```

---

## M. `apps/validation/views.py` — pass `jira_types` to the Verify page (Req 2)

Find:

```python
    return render(request, "verify.html", {
        "nav": "verify",
        "tools": ToolConfig.objects.filter(is_active=True),
        "automation_types": AutomationType.objects.filter(is_active=True),
        "result_run": result_run,
        "history": history,
    })
```

Replace with:

```python
    from apps.adminconfig.models import JiraType
    return render(request, "verify.html", {
        "nav": "verify",
        "tools": ToolConfig.objects.filter(is_active=True),
        "automation_types": AutomationType.objects.filter(is_active=True),
        "jira_types": JiraType.objects.filter(is_active=True),
        "result_run": result_run,
        "history": history,
    })
```
