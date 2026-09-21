# EDCS-Gate — File & Repository Nomenclature and Quality Guidelines

**Version:** 1.0
**Applies to:** All automation handover packages verified through EDCS-Gate
(In-House, eNable, MATE, RPA) and their supporting ERIDOC document folders and
Bitbucket repositories.

This document is the reference standard the ERIDOC and Bitbucket scanners are
tuned against. Following it is the fastest way to get a **PASS** on the first
verification attempt.

---

## 1. Guiding principles

1. **Predictable** — a reviewer (or a scanner) can locate any artifact from its
   name alone.
2. **Traceable** — every file and repository maps back to a JIRA ID
   (Story or Enhancement) and a customer/automation.
3. **Consistent** — the same artifact type is named the same way everywhere.
4. **Clean** — no scratch files, secrets, credentials, or personal data in the
   handover package.

---

## 2. JIRA identifiers

| Type | Format | Example | Notes |
|------|--------|---------|-------|
| Story (parent) | `PROJ-1234` | `ACE-5821` | Uppercase project key, hyphen, number. |
| Enhancement | `PROJ-1299` **under** parent `PROJ-1234` | `ACE-6002` under `ACE-5821` | Each enhancement is verified/scheduled independently but linked to its parent Story. |

- A JIRA ID **must** match the pattern `^[A-Z][A-Z0-9]+-\d+$`.
- For an **Enhancement**, record the parent Story ID in the *Parent JIRA* field
  so multiple enhancements can be grouped under one Story.

---

## 3. File nomenclature

### 3.1 General rule

```
<JIRA_ID>_<CUSTOMER>_<AUTOMATION_NAME>_<ARTIFACT_TYPE>_<REV>.<ext>
```

- Use **UPPER_SNAKE_CASE** for the machine-readable segments.
- Separator between segments is a single underscore `_`.
- No spaces, no `&`, `#`, `%`, parentheses, or non-ASCII characters in file names.
- Revision is `RevA`, `RevB`, … or a semantic version `v1.0`, `v1.1`.

**Example**

```
ACE-5821_BhartiAirtel_ACE_RAN_TRX_TEST_REPORT_RevB.pdf
ACE-5821_BhartiAirtel_ACE_RAN_TRX_DESIGN_SPEC_v1.2.docx
```

### 3.2 Mandatory document artifact types (ERIDOC)

| Artifact key | Meaning | Typical ext |
|--------------|---------|-------------|
| `DESIGN_SPEC` | Solution/technical design specification | `.docx`, `.pdf` |
| `TEST_REPORT` | Test execution report / evidence | `.pdf`, `.xlsx` |
| `RELEASE_NOTE` | Release notes for the delivered version | `.pdf`, `.md` |
| `USER_GUIDE` | Operator / user guide | `.pdf`, `.docx` |
| `HANDOVER_NOTE` | Handover summary & known issues | `.pdf`, `.docx` |

> The authoritative, per-tool checklist lives in
> `vendor/edcs_core/config/mandatory_documents.yaml`. If a document type is
> listed there it **must** be present in the ERIDOC folder, correctly named,
> and non-blank.

### 3.3 Quality rules the scanner enforces

- **Not blank / not title-page-only / not image-only** — every mandatory
  document must contain real content.
- **Reasonable size** — suspiciously small files are flagged for manual review.
- **Correct folder** — files must sit in the ERIDOC folder that matches the
  JIRA ID (or the explicit ERIDOC folder path supplied on the Verify page).
- **Latest revision only** — avoid committing multiple stale revisions of the
  same artifact in the same folder.

---

## 4. Repository nomenclature (Bitbucket)

### 4.1 Repository name

```
<team-or-domain>-<customer>-<automation-name>
```

- **lowercase-kebab-case**, ASCII only.
- No customer secrets or ticket numbers in the repo name.

**Example:** `ran-bhartiairtel-ace-trx`

### 4.2 Branch naming

| Purpose | Pattern | Example |
|---------|---------|---------|
| Feature | `feature/<JIRA_ID>-<slug>` | `feature/ACE-5821-trx-parser` |
| Bugfix | `bugfix/<JIRA_ID>-<slug>` | `bugfix/ACE-6002-null-guard` |
| Release | `release/<version>` | `release/1.2.0` |

### 4.3 Commit messages

```
<JIRA_ID>: <imperative summary>

<optional body explaining what & why>
```

**Example:** `ACE-5821: add TRX threshold validation`

### 4.4 Required repository hygiene (scanner enforced)

- **No hard-coded secrets** — no passwords, tokens, API keys, private keys,
  connection strings, or `.pem`/`.key` files committed.
- **No internal IPs / hostnames** hard-coded in source — use configuration.
- **No credentials in history** — rotate and purge if ever committed.
- **`.gitignore`** present and excluding build output, virtualenvs, `.env`,
  local IDE files, and large binaries.
- **README** present, describing purpose, setup, and the owning JIRA/automation.

---

## 5. Recommended repository structure

```
<repo-root>/
├── README.md
├── .gitignore
├── src/                 # application / automation source
├── config/              # externalised configuration (no secrets)
│   └── settings.example.*   # sample config, real values injected at runtime
├── tests/               # automated tests
├── docs/                # design notes, diagrams
└── scripts/             # helper scripts
```

---

## 6. Pre-handover checklist

Before running EDCS-Gate verification, confirm:

- [ ] JIRA ID (and Parent JIRA for enhancements) is correct.
- [ ] All mandatory ERIDOC documents are present, named per §3, and non-blank.
- [ ] ERIDOC folder path is correct (if supplying it explicitly on Verify).
- [ ] Repository has no secrets, keys, or hard-coded internal IPs.
- [ ] `.gitignore` and `README.md` are present.
- [ ] Branch and latest commit follow §4.2 / §4.3.
- [ ] Stale/duplicate document revisions removed.

Passing this checklist should yield a green **PASS** on both the ERIDOC and
Bitbucket scanners.

---

*This is a sample standard. Tailor the mandatory-document list and secret rules
to your programme by editing `vendor/edcs_core/config/mandatory_documents.yaml`
and `secret_rules.yaml`, then keep this document in sync.*
