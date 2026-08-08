"""Line-oriented secret scanning: custom ruleset + entropy engine.

detect-secrets plugins can be layered in via the adapter at the bottom;
findings from all engines are normalized to Finding and de-duplicated."""
from __future__ import annotations

import logging
import time

from edcs.code_scanner.entropy import high_entropy_candidates
from edcs.models import Finding, Severity
from edcs.regex_engine.engine import FILE_SCAN_TIMEOUT_S, RuleSet, downgrade
from edcs.utils.masking import mask_line, mask_secret

log = logging.getLogger(__name__)


def scan_lines(relpath: str, lines: list[str], rs: RuleSet) -> list[Finding]:
    findings: list[Finding] = []
    deadline = time.monotonic() + FILE_SCAN_TIMEOUT_S
    path_dg = rs.path_downgraded(relpath)

    for lineno, line in enumerate(lines, start=1):
        if time.monotonic() > deadline:
            findings.append(Finding(
                Severity.INFO, "SCAN_TIMEOUT", relpath,
                "Per-file scan budget exceeded; remainder of file skipped",
                "Review this file manually; consider excluding generated files.",
                "EDCS-SCAN-001", lineno))
            break
        if len(line) > 5000:
            line = line[:5000]  # minified blobs: bound the work

        for rule in rs.rules:
            try:
                m = rule.pattern.search(line, timeout=1.0)
            except TimeoutError:
                continue
            if not m:
                continue
            secret = m.groups()[-1] if m.groups() and m.groups()[-1] else m.group(0)
            bare = secret.strip().strip("\"'")
            if bare.startswith(("${", "{{", "%(", "$(")) or (
                    bare.startswith("<") and bare.endswith(">")):
                continue  # env/template reference, not a literal secret
            sev, reason = rule.severity, rule.reason
            if rs.is_placeholder(secret):
                sev, reason = Severity.INFO, reason + " (placeholder value - downgraded)"
            if path_dg:
                sev = downgrade(sev)
                reason += " (test/fixture path - downgraded one level)"
            findings.append(Finding(sev, "SECRET", relpath, reason,
                                    rule.recommendation, rule.id, lineno,
                                    mask_line(line, secret)))
            break  # one rule hit per line is enough - avoids duplicate noise

        else:
            for cand in high_entropy_candidates(line, rs.entropy_cfg):
                sev = Severity.MEDIUM if not path_dg else Severity.LOW
                findings.append(Finding(
                    sev, "SECRET", relpath,
                    "High-entropy string (possible encoded secret)",
                    "Verify; if a secret, rotate it and move to a secret store.",
                    "EDCS-SEC-009", lineno, mask_secret(cand)))
                break
    return findings


def detect_secrets_findings(relpath: str, abspath: str, rs: RuleSet) -> list[Finding]:
    """Optional layer: Yelp detect-secrets plugins. Fails soft if unavailable.

    Disabled by default (rs.enable_detect_secrets_plugin) — this plugin runs
    with its own hardcoded thresholds and flags long file paths / numeric IDs
    as "Base64 High Entropy String" false positives. Enable in
    secret_rules.yaml only if you want the extra (noisy) coverage."""
    if not rs.enable_detect_secrets_plugin:
        return []
    try:
        from detect_secrets.core.scan import scan_file
        from detect_secrets.settings import default_settings
    except ImportError:
        return []
    out: list[Finding] = []
    try:
        with default_settings():
            for ps in scan_file(abspath):
                sev = Severity.HIGH
                if rs.path_downgraded(relpath):
                    sev = downgrade(sev)
                out.append(Finding(
                    sev, "SECRET", relpath,
                    f"detect-secrets: {ps.type}",
                    "Rotate the secret; store it in vault/.env injected at runtime.",
                    "EDCS-DS-001", ps.line_number, ""))
    except Exception as e:  # never let a plugin kill the scan
        log.debug("detect-secrets failed on %s: %s", relpath, e)
    return out


def dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple] = set()
    out = []
    for f in sorted(findings, key=lambda f: -f.severity.rank):
        key = (f.file, f.line, f.category)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
