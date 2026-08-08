# Scanner Integration — EDCS v1.0.1

Status: **wired and verified**. `apps/scanners/eridoc_adapter.py` and
`apps/scanners/bitbucket_adapter.py` call your real EDCS v1.0.1 engine
(vendored at `vendor/edcs_core`, installed as the `edcs` package) — not
stubs. This was confirmed end-to-end in this build: the real
`DocumentScanner` loaded your actual mandatory-document checklist (MOP,
SOLUTION_DESIGN, HLD, LLD, TROUBLESHOOTING_GUIDE, UAT_LOGS, UAT_SIGNOFF,
ROLLBACK_PLAN, TEST_EVIDENCE, RELEASE_NOTES, USER_GUIDE) and the host
allow-list check correctly used EDCS's own `SecurityError`.

## What "wired" means concretely

| | Before | Now |
|---|---|---|
| `eridoc_adapter._run_real()` | `NotImplementedError` placeholder | Calls `edcs.document_scanner.scanner.DocumentScanner(settings).scan(jira_id)` directly |
| `bitbucket_adapter._run_real()` | `NotImplementedError` placeholder | Calls `edcs.code_scanner.scanner.CodeScanner(settings).scan(repo_url, stats)` directly |
| Repo host allow-list | Our own regex guess | EDCS's own `validate_repo_url()` / `BITBUCKET_ALLOWED_HOSTS` — one source of truth |
| Requirements | — | `vendor/edcs_core` added as an editable install; all its dependencies (GitPython, PyMuPDF, python-docx, detect-secrets, etc.) added to `requirements.txt` |

## Turning it on

1. `pip install -r requirements.txt` — this now also runs
   `pip install -e ./vendor/edcs_core`, pulling in the scanner engine and
   every library it needs (verified: installs cleanly from PyPI).
2. Fill the EDCS block in `.env`:
   ```
   ERIDOC_REST_URL=https://<your-d2rest-host>/d2rest
   ERIDOC_REPOSITORY=eridoca
   ERIDOC_USERNAME=svc-edcs
   ERIDOC_PASSWORD=<real password>
   BITBUCKET_USERNAME=svc-edcs
   BITBUCKET_TOKEN=<real token>
   BITBUCKET_ALLOWED_HOSTS=bitbucket.<your-domain>.com
   ```
3. Set `DEMO_MODE=False`.
4. Restart the app (and worker, if running Celery separately).

That's it — no code changes needed. `apps/scanners/*_adapter.py` already
does the real call once `DEMO_MODE=False`.

## Why you don't need to touch `MANDATORY_DOCS_FILE` / paths

EDCS's own settings default to hardcoded Linux paths (`/var/lib/edcs/...`).
`config/settings.py` in EDCS-Gate sets cross-platform defaults for you
(verified working on this sandbox's Linux path resolution; same logic
applies on Windows since it's built from `pathlib.Path`):

```python
MANDATORY_DOCS_FILE → vendor/edcs_core/config/mandatory_documents.yaml
SECRET_RULES_FILE   → vendor/edcs_core/config/secret_rules.yaml
TMP_DIR / CLONE_DIR / REPORT_DIR / LOG_DIR / HISTORY_DB_URL → var/edcs/... under the project root
```
Override any of these in `.env` if you want EDCS's own history DB, clone
staging area, etc. to live somewhere else (e.g. a faster disk for clones).

## How results map into the EDCS-Gate report

EDCS returns a flat list of `Finding` objects (severity, category, reason,
**recommendation**, rule_id). The adapters classify each one:

**ERIDOC (`eridoc_adapter.py`)**
| EDCS category | EDCS-Gate bucket |
|---|---|
| `DOC_FOLDER_MISSING`, `DOC_FOLDER_EMPTY`, `DOC_MISSING` | Missing documents |
| `DOC_BLANK`, `DOC_TITLE_PAGE_ONLY`, `DOC_IMAGE_ONLY` | Blank documents |
| any other, severity ≥ HIGH | Failed checks |
| severity < HIGH (`DOC_NO_OWNER`, `DOC_NAME_FUZZY`, `DOC_SUSPECT_SMALL`, …) | Warnings |

Overall FAILED if: compliance score < `COMPLIANCE_PASS_SCORE` (default 90),
OR any HIGH+/CRITICAL finding, OR any missing/blank document — same
verdict logic as the original `ScanResult.finalize()` in `edcs/models.py`,
reproduced here since the adapter calls `DocumentScanner` directly rather
than the combined `orchestrator.run_job()` (which always requires a repo
URL — not true for RPA/eNable/Mate).

**Bitbucket (`bitbucket_adapter.py`)**
| Condition | Bucket |
|---|---|
| severity ≥ `SEVERITY_FAIL_THRESHOLD` (default HIGH) | Failed checks |
| below threshold | Warnings |

## The "suggest correction" requirement

Every EDCS `Finding` already carries a human-written `recommendation`
(e.g. *"Upload PROJ-1234_RELEASE_NOTES.<ext> to the ERIDOC folder"* or
*"Move the credential to a secrets manager and rotate the exposed key"*).
The adapters preserve this field on every item; `report.html` and
`report_pdf.html` render it as a **💡 Suggested fix** callout under each
failed/missing/blank finding — so a failed validation already tells the
Scrum Master both what's wrong and what to do about it, with zero extra
work beyond what EDCS already computes.

## Error handling — retryable vs terminal

EDCS's own `EridocError` carries a `.retryable` flag (set by its internal
`tenacity`-based HTTP retry logic once those retries are exhausted); EDCS's
`CloneError` (disk space, git clone timeout) is treated as retryable by
the adapter. Both get mapped to `TransientScannerError`, which is the
exception our Celery task (`apps/validation/tasks.py`) automatically
retries (3 attempts, exponential backoff) before giving up and marking the
run `ERROR`. EDCS's `SecurityError` (bad JIRA pattern, disallowed host) is
never retried — it's a terminal, config/input problem, and the run ends
`ERROR` immediately so it's never silently treated as a PASS.

## Platform notes

- **GitPython** needs `git` on PATH (already true if you can already run
  `git clone` manually on the box).
- **python-magic** needs `libmagic`; on Windows `requirements.txt` installs
  `python-magic-bin` instead (bundles the binary), on Linux it installs
  the regular `python-magic` package that links the system's `libmagic`.
- Everything else (PyMuPDF, python-docx, python-pptx, openpyxl,
  msoffcrypto-tool, extract-msg, ruamel.yaml, defusedxml, python-hcl2,
  rapidfuzz, detect-secrets, regex) installs from prebuilt wheels on both
  platforms — confirmed no compiler was needed in this build/test.

## What's NOT changed

- Tool → scanner routing (`ToolConfig`), the parallel Celery chord, the
  scheduler, Graph integration — none of that changed. Only the two
  adapter files and the settings' path defaults were touched.
- EDCS's own mail intake / IMAP listener / SMTP mailer / history SQLite DB
  are part of the vendored package but **not used** by EDCS-Gate — we call
  `DocumentScanner`/`CodeScanner` directly rather than the full
  `orchestrator.run_job()` + mailer pipeline, since EDCS-Gate has its own
  report/notification layer already (§ architecture doc).

## Since this was written: two follow-ups worth knowing about

**Detect-secrets plugin noise.** A separate Yelp `detect-secrets` plugin
layer (rule `EDCS-DS-001`) was found to false-positive heavily on long file
paths and numeric node/archive IDs (common in this codebase) — it's off by
default now via `enable_detect_secrets_plugin: false` in
`secret_rules.yaml`. The named `EDCS-SEC-00x` regex rules (passwords, keys,
connection strings, etc.) are unaffected and remain the primary detection
layer. Flip that flag to `true` only if you want the extra, noisier
coverage back.

**Document-matching tuning.** If real scans are flagging documents as
missing that clearly exist in ERIDOC, the mismatch is almost always in
`mandatory_documents.yaml`'s `aliases:` list not matching your team's
actual file-naming conventions — see `ERIDOC-MATCHING-TUNING-GUIDE.md` for
how the matcher works and how to verify/fix alias coverage against real
filenames before trusting a compliance score.
