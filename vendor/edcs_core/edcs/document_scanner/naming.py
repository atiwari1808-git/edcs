"""Filename <-> Jira ID validation."""
from __future__ import annotations

import re

from edcs.models import Finding, Severity

_ANY_JIRA = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,7}\b")


def check_name(doc_name: str, jira_id: str) -> list[Finding]:
    findings: list[Finding] = []
    # exact token, look-arounds prevent ABCD-12345 passing for ABCD-1234
    token = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(jira_id)}(?!\d)")
    if not token.search(doc_name):
        other = [m for m in _ANY_JIRA.findall(doc_name.upper()) if m != jira_id.upper()]
        if other:
            findings.append(Finding(
                severity=Severity.HIGH, category="DOC_WRONG_JIRA", file=doc_name,
                rule_id="EDCS-DOC-012", line=None,
                reason=f"Filename references different Jira ID {other[0]} (expected {jira_id})",
                recommendation=f"Verify this document belongs to {jira_id}; rename accordingly."))
        else:
            findings.append(Finding(
                severity=Severity.MEDIUM, category="DOC_NAMING", file=doc_name,
                rule_id="EDCS-DOC-010", line=None,
                reason=f"Filename does not contain the Jira ID {jira_id}",
                recommendation=f"Rename to {jira_id}_<DocType>.<ext>"))
    if any(ord(c) > 127 for c in doc_name):
        findings.append(Finding(
            severity=Severity.LOW, category="DOC_NAMING", file=doc_name,
            rule_id="EDCS-DOC-011", line=None,
            reason="Filename contains non-ASCII characters",
            recommendation="Use ASCII letters, digits, hyphen and underscore only."))
    return findings
