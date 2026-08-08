# EDCS — ERIDOC Document & Code Scanner

Automated compliance pipeline: notification email in → ERIDOC document
validation + Bitbucket secret/IP scanning → PASS/FAIL report email out.

See `docs`/design specification for full architecture. Quick start:

```bash
make dev                 # venv + editable install with dev tools
cp .env.example .env     # fill in credentials; chmod 600 .env
make test                # unit tests (no network needed)
# manual scan (Phase-1 workflow):
.venv/bin/python scripts/run_once.py --jira ABCD-1234 \
    --repo https://bitbucket.xxx.com/projects/OSS/repos/project --no-mail
# daemons:
make run-listener        # IMAP intake
make run-worker          # scan worker (run N of these)
```

Layout: `edcs/` (modules) · `config/` (policy YAML + report templates) ·
`systemd/` (RHEL service units) · `scripts/` (CLI) · `tests/` (pytest).
