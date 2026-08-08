# Tuning the ERIDOC Document Scanner Matching — Where & How

## The one-line answer

**95% of tuning happens in one YAML file — no code, no regex:**

```
vendor/edcs_core/config/mandatory_documents.yaml
```

(or wherever `MANDATORY_DOCS_FILE` in `.env` points — see §4). The scanner
re-reads this file **on every scan**, so changes take effect on the next
validation with no restart.

The only real regexes live in `edcs/document_scanner/mandatory.py`
(`normalize()`), and you almost never need to touch them — see §3.

---

## 1. How matching actually works (so the YAML makes sense)

For every file in the JIRA's ERIDOC folder, the scanner:

1. Takes the **filename** (ERIDOC `object_name` — NOT the "Title" column),
2. **Normalizes** it: strips the JIRA id, replaces `_ - . +` with spaces,
   strips version tokens (`v1.0`, `2.3`), lowercases.
   `MoP_v1.0_To Save config dump of Cisco DNS.docx`
   → `mop to save config dump of cisco dns`
3. Checks each checklist entry's **aliases**: match if the normalized name
   **equals** an alias or **contains** it as a substring (case-insensitive).
4. If nothing matched, tries **fuzzy matching** (`token_set_ratio`) and
   accepts a hit at ≥ `fuzzy_ratio` (default 88) — flagged with a
   "matched only via fuzzy" LOW warning.
5. Any checklist entry with no matching file → **DOC_MISSING** (HIGH) →
   run FAILS.

So "changing the regex" = **adding aliases that match your real file
naming**, and occasionally adjusting `fuzzy_ratio`.

---

## 2. What your ACTUAL folders show (from your two screenshots)

I traced every file in ASB-11025 and ASB-10944 through the current rules:

| Your real file | Current outcome | Why |
|---|---|---|
| `HLD_ASB-11025_ACE_PCN_...` / `HLD_ASB-10944.docx` | ✅ HLD | contains alias `hld` |
| `MoP_v1.0_...` / `MOP_ver1.1_...` | ✅ MOP | contains `mop` |
| `LLD.xlsx` | ✅ LLD | contains `lld` |
| `Troubleshooting and Execution Guide_...` / `Troubleshooting_Guide_...` | ✅ TSG | contains `troubleshooting` |
| `Logs.zip` | ✅ UAT_LOGS (fuzzy) | `logs` ⊂ `uat logs` → fuzzy 100, with a LOW naming warning |
| **`Solution-ASB-11025 Save Configuration Dump...docx`** | ❌ **MISSED → false "SOLUTION_DESIGN missing"** | none of `Solution Design`/`SD`/`SolutionDesign` is contained in "solution save configuration dump…"; fuzzy score too low |
| **`Final Sign-off ASB-11025 ....msg`** | ⚠️ **borderline** (~fuzzy threshold) | aliases are `UAT Sign-off`/`Sign Off Mail`; your files say just "Final Sign-off" — may miss depending on the rest of the name |
| **`Execution_Guide_ASB-10944_...docx`** | ❌ unmatched | "execution guide" isn't an alias of anything |
| **`22April_report1_177683372199.zip`** (Title: *UAT_LOGS_ASB-10944*) | ❌ unmatched | matching uses the **filename**, and the UAT hint is only in the ERIDOC *Title* column — see §3b |
| `Review_Checklist_Usecase_...xlsx`, `resources.zip`, `RESOURCES.zip` | ignored (not in checklist) | fine, unless Review Checklist should be mandatory for you |
| — | ❌ ASB-11025 would also fail on: LLD, UAT_LOGS, ROLLBACK_PLAN, TEST_EVIDENCE, RELEASE_NOTES, USER_GUIDE | those checklist entries have no file at all in that folder |

**Two separate problems, two separate fixes:**
- **Aliases don't match your naming** → fix in YAML (§2a).
- **The checklist demands 11 documents your process doesn't actually
  produce** (Rollback Plan, Test Evidence, Release Notes, User Guide, …) →
  a **policy decision**: delete those entries or your scans will fail
  forever (§2b).

### 2a. Ready-to-paste alias fixes (matches your observed naming)

```yaml
  - key: SOLUTION_DESIGN
    aliases: ["Solution Design", "SolutionDesign", "Solution"]   # + "Solution"
    weight: 8
    min_chars: 500
  - key: UAT_SIGNOFF
    aliases: ["UAT Sign-off", "UAT Signoff", "Sign Off Mail",
              "Final Sign-off", "Final Sign off", "Sign-off"]    # + Final Sign-off forms
    weight: 8
    min_chars: 50
  - key: TROUBLESHOOTING_GUIDE
    aliases: ["Troubleshooting", "Troubleshooting Guide", "TSG",
              "Execution Guide"]     # + Execution Guide (or make it its own key, below)
    weight: 6
    min_chars: 200
  - key: UAT_LOGS
    aliases: ["UAT Logs", "UAT Log", "UAT_Logs", "Logs"]         # + bare "Logs"
    weight: 8
    min_chars: 200
```

If Execution Guide is a **separate** mandatory document (not just another
name for the troubleshooting guide), give it its own entry instead:
```yaml
  - key: EXECUTION_GUIDE
    aliases: ["Execution Guide", "ExecutionGuide"]
    weight: 8
    min_chars: 300
```

⚠️ **Alias caution:** short/broad aliases raise false-positive risk. Adding
`"Solution"` means *any* filename containing "solution" claims the
SOLUTION_DESIGN slot; `"Logs"` claims UAT_LOGS for any logs file. That's
usually acceptable (a wrong match still means "a plausibly-named document
exists"), but keep aliases as specific as your naming allows.

### 2b. Align the mandatory set with reality (decide as a team)

Delete (or keep, if they ARE required and just absent from these two
JIRAs) the entries your folders never contain:
`ROLLBACK_PLAN`, `TEST_EVIDENCE`, `RELEASE_NOTES`, `USER_GUIDE`, and
possibly `MOP` vs `SOLUTION_DESIGN` overlaps. And consider **adding**
what you clearly DO produce every time: `Review Checklist`
(`Review_Checklist_Usecase_...xlsx` appears in your folders), `Resources`
if it's compulsory.

Also relevant knobs in the same file:
- `weight:` — each doc's share of the compliance score (pass threshold =
  `COMPLIANCE_PASS_SCORE` in `.env`, default 90).
- `min_chars:` — below this extracted-text length ⇒ blank-document check.
- `matching: fuzzy_ratio: 88` — lower (e.g. 82) = more forgiving of odd
  names but more mismatch risk; raise to be stricter.
- `boilerplate_lines` / `signoff_keywords` — the blank/sign-off content
  heuristics.

---

## 3. When you DO need to touch code (rare)

File: `vendor/edcs_core/edcs/document_scanner/mandatory.py`

**(a) `normalize()` (the actual regexes)** — only if your filenames defeat
normalization. Current rules: strip JIRA id → `[_\-\.\+]+`→space →
strip `\bv?\d+(\.\d+)*\b` version tokens → collapse spaces. Example
change: your `MOP_ver1.1` leaves a stray "ver" token; to also strip
`ver1.1`-style versions, extend that one line:
```python
stem = re.sub(r"\b(?:v|ver|version)?\d+(\.\d+)*\b", " ", stem, flags=re.I)
```

**(b) Match on the ERIDOC *Title* as a fallback** — your
`22April_report1_...zip` is only identifiable by its Title
(`UAT_LOGS_ASB-10944`). Today the Title isn't even fetched. Two edits:
1. `edcs/eridoc_client/dql.py` (~line 37): add `d.title` to the SELECT
   list and carry it onto the result object.
2. `edcs/document_scanner/scanner.py` (~line 86):
   ```python
   key, fuzzy = match_document(r.name, jira_id, self.checklist)
   if not key and getattr(r, "title", ""):
       key, fuzzy = match_document(r.title, jira_id, self.checklist)
   ```
This is the highest-value code change if your team often uploads
meaningfully-titled but cryptically-named files.

*(For completeness: the CODE scanner's rules — passwords/secrets patterns —
are true regexes and live in `vendor/edcs_core/config/secret_rules.yaml`.
Different file, same "edit YAML, next scan picks it up" behaviour.)*

---

## 4. Keep your tuning safe from vendor updates

`config/settings.py` points `MANDATORY_DOCS_FILE` at the vendor copy *only
as a default*. Recommended: copy the YAML out of `vendor/` and point `.env`
at your own copy, so re-vendoring EDCS never overwrites your tuning:

```powershell
mkdir config\eridoc
copy vendor\edcs_core\config\mandatory_documents.yaml config\eridoc\
```
`.env`:
```
MANDATORY_DOCS_FILE=config/eridoc/mandatory_documents.yaml
```
(Relative paths resolve from where you run `manage.py` — the project root.
Use an absolute path if you run the worker from elsewhere.)

## 5. Verify a tuning change in 30 seconds (no full scan)

```powershell
python manage.py shell
```
```python
from edcs.config import get_settings
from edcs.document_scanner.mandatory import load_checklist, match_document
cl = load_checklist(get_settings().mandatory_docs_file)
for name in [
  "Solution-ASB-11025 Save Configuration Dump of all Cisco DNS at Storage Server.docx",
  "Final Sign-off ASB-11025 Save Configuration Dump.msg",
  "Execution_Guide_ASB-10944_Design-SCTP_M3UA Link Creation.docx",
  "22April_report1_177683372199.zip",
]:
    print(name, "->", match_document(name, "ASB-11025", cl))
```
Each line prints `(matched_key, fuzzy_used)` — `(None, False)` means that
file would trigger a DOC_MISSING for whatever entry it was supposed to
satisfy.
