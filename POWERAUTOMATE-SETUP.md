# Power Automate Scheduling — Setup Guide (Option A: email trigger)

EDCS-Gate no longer calls Microsoft Graph. When a Scrum Master books a
slot, the app sends **one structured email** to a trigger mailbox. A Power
Automate cloud flow watches that mailbox, extracts a JSON payload from the
email body, and creates the Teams meeting. No Azure AD app registration,
no admin consent.

```
Scrum Master → EDCS-Gate (slot + attendees) → SMTP relay
      → trigger mailbox → Power Automate flow → Teams meeting + invites
```

---

## Part 1 — What the app sends (already built, nothing to do)

Subject:
```
[EDCS-GATE-MEETING] ASB-10025 2026-07-14T10:00:00
```

Body (plain text — human-readable header + machine block):
```
EDCS-Gate meeting request. Do not edit — processed automatically by Power Automate.

JIRA: ASB-10025
When: 2026-07-14T10:00:00 – 2026-07-14T10:30:00 (Asia/Kolkata)
Organizer: abhishek.tiwari@ericsson.com
Attendees: abhishek.tiwari@ericsson.com;vaishali.saini@ericsson.com;pmo@ericsson.com

###EDCS-JSON-START###{"version":3,"meeting_id":"...","ref":"5a39a53af74e","jira_id":"ASB-10025","automation_name":"ACE_RAN_ERICSSON_BL_TRX","subject":"Handover Call – MATE | ASB-10025 – ACE_RAN_ERICSSON_BL_TRX [EDCSREF-5a39a53af74e]","body_html":"<p>...</p>","start":"2026-07-14T10:00:00","end":"2026-07-14T10:30:00","timezone":"Asia/Kolkata","organizer_email":"abhishek.tiwari@ericsson.com","attendees":["..."],"attendees_semicolon":"a@x;b@x","cc_semicolon":""}###EDCS-JSON-END###
```

Key properties the flow relies on:
- Subject always starts with `PA_SUBJECT_PREFIX` (default `[EDCS-GATE-MEETING]`)
- The JSON is a single line between `###EDCS-JSON-START###` and
  `###EDCS-JSON-END###` — plain-text tokens, not angle-bracket tags.
  (Angle brackets were tried first and failed: Exchange/Outlook store mail
  bodies as HTML internally, so `<EDCS-JSON>` gets silently stripped as an
  unrecognized HTML tag before the flow ever sees it, corrupting extraction.)
- `start`/`end` are local naive datetimes + a separate IANA `timezone`
  field (exactly what Outlook's Create-event action wants)
- `attendees_semicolon` is pre-joined with `;` — paste-ready for the
  Outlook action's attendee field, no loop needed
- **Compulsory attendees are already merged in by the backend** (from
  Admin → Meeting templates → `default_attendees`), plus the organizer
  themself — the flow never has to add anyone

## Part 2 — .env configuration

```
SCHEDULER_MODE=powerautomate_email
PA_TRIGGER_MAILBOX=edcs-gate-scheduler@ericsson.com   # the mailbox the flow watches
PA_SUBJECT_PREFIX=[EDCS-GATE-MEETING]
EMAIL_HOST=<your internal SMTP relay>                 # required in this mode
EMAIL_PORT=25
DEFAULT_FROM_EMAIL=edcs-gate-noreply@ericsson.com
```

**Mailbox recommendation:** ask IT for a **shared mailbox** (e.g.
`edcs-gate-scheduler@`) rather than watching a personal inbox. The flow
then runs under a connection that has access to that shared mailbox, and
the whole pipeline survives any one person leaving the team. A personal
mailbox + an Outlook rule moving mails to a folder also works for a pilot.

## Part 3 — Build the flow (≈15 minutes)

Go to **make.powerautomate.com → Create → Automated cloud flow**.

### Step 1 — Trigger: "When a new email arrives (V3)" (Office 365 Outlook)
- **Folder:** Inbox (of the shared mailbox — use "When a new email arrives
  in a shared mailbox (V2)" if using one)
- Show advanced options →
  - **Subject Filter:** `[EDCS-GATE-MEETING]`
  - **Importance:** Any · **Include Attachments:** No

### Step 2 — Security gate: Condition
The subject filter alone is spoofable — anyone who can email the mailbox
could trigger meeting creation. Add a **Condition**:
- `From` (dynamic content) **is equal to** `edcs-gate-noreply@ericsson.com`
  (your `DEFAULT_FROM_EMAIL`)
- Put ALL remaining steps in the **Yes** branch. In the **No** branch:
  optionally "Mark as read" and Terminate (Status: Cancelled).

### Step 3 — Action: "Html to text" (Content Conversion)
Even though the app sends plain text, Outlook triggers often hand you an
HTML-ified body. This normalizes it.
- **Content:** `Body` (dynamic content from the trigger)

### Step 4 — Action: "Compose" — extract the JSON between the markers
- **Inputs** (Expression tab, paste exactly):
```
trim(first(split(last(split(body('Html_to_text'), '###EDCS-JSON-START###')), '###EDCS-JSON-END###')))
```
(If you renamed step 3, replace `Html_to_text` with its name,
spaces→underscores.)

### Step 5 — Action: "Parse JSON"
- **Content:** `Outputs` of the Compose step
- **Schema** (paste as-is):
```json
{
  "type": "object",
  "properties": {
    "version":            {"type": "integer"},
    "meeting_id":         {"type": "string"},
    "jira_id":            {"type": "string"},
    "automation_name":    {"type": "string"},
    "subject":            {"type": "string"},
    "subject_with_ref":   {"type": "string"},
    "ref": {"type": "string"},
    "body_html":          {"type": "string"},
    "start":              {"type": "string"},
    "end":                {"type": "string"},
    "timezone":           {"type": "string"},
    "organizer_email":    {"type": "string"},
    "attendees":          {"type": "array", "items": {"type": "string"}},
    "attendees_semicolon":{"type": "string"},
    "cc_semicolon":       {"type": "string"}
  },
  "required": ["subject", "start", "end", "timezone", "attendees_semicolon"]
}
```

### Step 6 — Action: "Create a Teams meeting" (Microsoft Teams connector)
*(You chose the Teams action rather than Outlook "Create event" — the field
mapping below matches it. Both create a calendar item with a Teams link; the
Teams action's item is still findable/deletable through Outlook's
Get events / Delete event actions, which is what the cancel flow uses.)*
- **Calendar id:** Calendar (of the account/shared mailbox creating meetings)
- **Subject / Title:** `subject_with_ref` (from Parse JSON) — **not** `subject`.
  This stamps the correlation marker `[EDCSREF-xxxxxxxxxxxx]` into the meeting
  title; the cancel flow finds the meeting by searching for that marker, which
  survives reschedules and partial renames.
  ⚠ The marker deliberately uses `EDCSREF-` (hyphen), never `EDCS#` (hash).
  `#` is a URL-reserved character; Power Automate's Get-events OData filter
  builds `$filter` into a request URL without percent-encoding it, so a raw
  `#` gets read as a URL-fragment delimiter and silently truncates everything
  after it — corrupting the filter and causing "unterminated string literal"
  errors. Keep the marker alphanumeric-and-hyphen only.
- **Start time:** `start` · **End time:** `end`
- **Time zone:** ⚠ this field wants a **Windows** timezone name, not IANA.
  If all your meetings are IST, just hardcode
  `(UTC+05:30) Chennai, Kolkata, Mumbai, New Delhi` here.
  (Multi-timezone later? Add a Switch on the payload's `timezone` field
  mapping IANA → Windows names.)
- **Required attendees:** `attendees_semicolon` (developers + scrum masters + compulsory + organizer)
- **Optional attendees** (advanced options): `cc_semicolon` (the CC field from the booking form)
- Show advanced options →
  - **Body:** `body_html` · **Is HTML:** Yes
  - **Is online meeting:** **Yes** · **Online meeting provider:** *Teams for business*
    ← this is what makes it a real Teams meeting with a join link
  - **Reminder:** 15 (or your preference)

Exchange sends the invitations to every attendee automatically — including
the organizer, who is always in the attendee list.

### Step 6b — Action: "Create item" (SharePoint) — index the event id
**Do this step.** The cancel flow needs to find this exact event later, and
on many tenants the Outlook **"Get events"** action is blocked by an
Advanced Connector Policy / DLP rule (`Request blocked due to data loss
prevention (DLP) or advanced connector policies (ACP)`) even though
Create/Delete on the same connector are allowed. Indexing the id yourself
in SharePoint sidesteps that entirely — see Part 6 below for full setup;
in short:
- **Site Address:** your SharePoint site · **List Name:** `EDCSMeetings`
  (two columns: `Title` single line of text, `EventId` single line of text)
- **Title:** `ref` (from Parse JSON)
- **EventId:** `Id` — the output of the **Create a Teams meeting** step above

### Step 7 (optional but recommended) — Failure alert
Add a parallel branch or configure-run-after (⋯ → *Configure run after* →
check "has failed") on Step 6 → "Send an email (V2)" to yourself/the SM:
`Failed to schedule: ` + `subject`. Without this, a failed flow run dies
silently inside Power Automate's run history.

### Step 8 — Save, then test end-to-end
1. In EDCS-Gate, run a validation that passes → book a slot.
2. Confirmation screen shows **"✉ Meeting request sent"**.
3. Within ~1 minute the flow fires (check *My flows → run history*).
4. The Teams invite lands in every attendee's Outlook.

## Part 4 — Who "owns" the meeting (important behavioral difference)

In Graph mode, the meeting was created **as the Scrum Master**. In this
mode it's created by **the flow connection's account** (the shared
mailbox / whoever built the flow). Consequences:
- The organizer shown in Outlook is that account, not the SM. The SM is a
  required attendee and gets the invite like everyone else.
- Rescheduling/cancelling happens in Outlook by whoever owns that
  calendar — EDCS-Gate cannot cancel it (no API access, by definition).
- Meeting history in EDCS-Gate shows status **REQUESTED** (request sent),
  not CONFIRMED — the app has no return channel to learn the outcome or
  the join URL. The invite in Outlook is the source of truth.

## Part 5 — Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Book → error "PA_TRIGGER_MAILBOX is not set" | Fill it in `.env`, restart |
| Book succeeds but flow never fires | Trigger mail not arriving: check SMTP relay logs; confirm the subject filter string matches `PA_SUBJECT_PREFIX` exactly (including brackets); check junk folder of the trigger mailbox |
| Flow fires but fails at Parse JSON | Step 4 expression name mismatch (`Html_to_text`), or someone forwarded/edited the mail. Open the failed run → check Compose output — it must be pure JSON `{...}` |
| Event created at wrong time | Step 6 Time zone field left on UTC — set the Windows IST zone |
| Attendees empty | You mapped `attendees` (the array) into the attendee field instead of `attendees_semicolon` |
| Random people can create meetings by emailing the mailbox | You skipped Step 2 (sender check). Add it. |

---

# Cancel flow — [EDCS-CANCEL] (new in v8)

When a user clicks **Cancel** on a booking in the dashboard, EDCS-Gate sends a
second kind of trigger email (same mailbox, different subject prefix):

Subject: `[EDCS-CANCEL] Handover Call – ASB-10944 2026-07-20T15:00:00`
Body: same structure as the create trigger — human-readable header + single-line
JSON between `###EDCS-JSON-START###` / `###EDCS-JSON-END###`:

```json
{"version":2,"action":"cancel","meeting_id":"<edcs uuid>","ref":"5a39a53af74e",
 "search_marker":"EDCSREF-5a39a53af74e","graph_event_id":"",
 "subject":"Handover Call – MATE | ASB-10944 – ACE_RAN_ERICSSON_BL_TRX [EDCSREF-5a39a53af74e]",
 "jira_id":"ASB-10944","automation_name":"ACE_RAN_ERICSSON_BL_TRX",
 "start":"2026-07-20T15:00:00","end":"2026-07-20T16:00:00","timezone":"Asia/Kolkata",
 "organizer_email":"vaishali.saini@ericsson.com"}
```

The flow identifies the event to cancel via the **SharePoint index** created
in Step 6b of the create flow (matched on `ref`) — not by searching Outlook
calendar events, since the Outlook **"Get events"** action is blocked by
Advanced Connector Policy / DLP on many tenants (`Request blocked due to
data loss prevention (DLP) or advanced connector policies (ACP)`). This
also happens to be more reliable than a calendar search: it's an exact ID
lookup, not a text match, so it can't be thrown off by someone renaming or
moving the meeting in Outlook afterwards.

## Build the flow (~10 min)

1. **Trigger** — "When a new email arrives (V3)" on the same mailbox,
   **Subject Filter:** `[EDCS-CANCEL]`
2. **Condition** — `From` equals your `DEFAULT_FROM_EMAIL` (same security gate
   as the create flow). All steps below go in the **Yes** branch.
3. **Html to text** — Content: trigger `Body`
4. **Compose** — Expression (fx editor!):
   `trim(first(split(last(split(body('Html_to_text'), '###EDCS-JSON-START###')), '###EDCS-JSON-END###')))`
5. **Parse JSON** — Content: `Outputs` (Compose). Schema:
```json
{"type":"object","properties":{
 "version":{"type":"integer"},"action":{"type":"string"},
 "meeting_id":{"type":"string"},"ref":{"type":"string"},
 "search_marker":{"type":"string"},"graph_event_id":{"type":"string"},
 "subject":{"type":"string"},"jira_id":{"type":"string"},
 "automation_name":{"type":"string"},
 "start":{"type":"string"},"end":{"type":"string"},
 "timezone":{"type":"string"},"organizer_email":{"type":"string"}},
 "required":["action","ref"]}
```
6. **Get items** (SharePoint) — Site Address / List Name: the same
   `EDCSMeetings` list from Step 6b. **Filter Query** (fx, use the
   Dynamic-content picker for the token rather than typing it, to avoid
   quote issues):
   ```
   Title eq '@{body('Parse_JSON')?['ref']}'
   ```
   Top Count: 1
7. **Delete event (V2)** (Office 365 Outlook) — Calendar id: the same
   calendar the create flow books into. **Id** (fx):
   ```
   first(body('Get_items')?['value'])?['EventId']
   ```
   (adjust `Get_items` to match your actual step name if renamed — spaces
   become underscores). Delete sends cancellations to all attendees
   automatically for organizer-owned meetings.
8. **Delete item** (SharePoint) — same list, Id:
   `first(body('Get_items')?['value'])?['ID']` — keeps the index table
   from growing forever now that the meeting's gone.
9. *(Optional but recommended)* **Send an email** ack to the organizer:
   "Your handover call '<subject>' on <start> was cancelled."

### If your tenant does NOT block "Get events" (no SharePoint needed)
Skip Step 6b in the create flow and steps 6/8 above entirely. Replace
step 7 with: **Get events (V4)** filtered on
`contains(subject,'@{body('Parse_JSON')?['search_marker']}')`, Top Count 1,
then **Delete event (V2)** with Id `first(body('Get_events_(V4)')?['value'])?['id']`.
Functionally equivalent — only worth doing if you've confirmed your DLP
policy actually allows it, since hitting the block mid-build wastes a
rebuild cycle.

## Notes
- With the SharePoint index (recommended path), the correlation key is the
  exact `EventId` stored at creation time — immune to the meeting being
  renamed or moved in Outlook afterwards, unlike subject/marker matching.
- If you're on the fallback subject-search path instead, the `[EDCSREF-...]`
  marker in the title is the correlation key — unique per meeting, survives
  reschedules, but breaks if someone manually strips the marker from the
  title in Outlook (the optional ack email makes that visible).
- `graph_event_id` remains in the payload as a spare field for a possible
  future upgrade (Feature-5 create-ack capturing Microsoft's own event id
  directly into the app's database) — not required by either approach above.

---

# Part 6 — SharePoint event-id index (recommended, avoids the DLP block)

One-time setup, ~5 minutes, needed once for both the create and cancel flows.

1. Go to your SharePoint site → **+ New → List → Blank list**.
   Name it `EDCSMeetings`.
2. Add a column **`EventId`** (type: **Single line of text**). The list's
   built-in `Title` column is reused as-is for the `ref` value — no need to
   rename it.
3. That's the whole list. No other columns, no views, no permissions
   changes needed beyond whoever/whatever account the flow's SharePoint
   connection runs as having edit access to that site.
4. Wire it into the two flows exactly as described above: **Create item**
   in the create flow (Step 6b), **Get items** + **Delete item** in the
   cancel flow (steps 6 and 8).

### Why this, and not just remembering the id in Django directly
The cleanest fix long-term is capturing the real event id back into
`Meeting.graph_event_id` in the app itself (the create flow emails it back,
the app reads that mailbox, stores it — see the `graph_event_id` note
above). That needs an inbound mail-reading path in Django that doesn't
exist yet — a real backend feature, not a flow change. The SharePoint list
gets you the same practical outcome (an exact-match id lookup, no DLP-
blocked action) **today**, entirely inside Power Automate, no app changes.
If you later build the Django-side inbound capture, you can retire the
SharePoint list at that point — say the word when you're ready for that
piece and I'll scope it as an app-side feature.

### Troubleshooting
| Symptom | Cause / fix |
|---|---|
| "Get items" also blocked by DLP | SharePoint is covered by a different policy than Outlook in most tenants, but confirm with whoever manages your DLP policies before building — ask specifically which connectors/actions are on the allow-list |
| Cancel flow finds nothing | Check the create flow's "Create item" step actually ran (open its run history) — if Step 6b was added after some meetings were already booked, older meetings simply aren't indexed and won't be cancellable via this flow (cancel them manually in Outlook once) |
| Multiple items returned for one `ref` | Shouldn't happen (`ref` is derived from a UUID) — if it does, check nothing is bulk-duplicating "Create item" calls (e.g. a retry policy re-running the whole flow) |
