"""Heuristic structure check: does an HLD/LLD/MOP contain the section
headings its template requires? Catches 'HLD-named file with meeting minutes'."""
from __future__ import annotations

from edcs.models import Finding, Severity

EXPECTED_SECTIONS = {
    "HLD": ["introduction", "architecture", "interfaces"],
    "LLD": ["introduction", "design", "configuration"],
    "MOP": ["prerequisite", "procedure", "rollback"],
    "ROLLBACK_PLAN": ["rollback", "verification"],
}


def check_structure(mkey: str, doc_name: str, text: str) -> list[Finding]:
    expected = EXPECTED_SECTIONS.get(mkey)
    if not expected or not text:
        return []
    low = text.lower()
    missing = [s for s in expected if s not in low]
    if len(missing) >= len(expected) - 1:  # almost nothing matches -> wrong artifact?
        return [Finding(
            severity=Severity.MEDIUM, category="DOC_TEMPLATE", file=doc_name,
            rule_id="EDCS-DOC-021",
            reason=f"Document matched '{mkey}' by name but lacks expected sections: "
                   f"{', '.join(missing)}",
            recommendation=f"Verify this is really the {mkey}; use the approved template.")]
    return []
