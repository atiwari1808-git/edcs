"""The optional Yelp detect-secrets layer (EDCS-DS-001) must also exclude the
Python `if __name__ == "__main__":` dry-run harness via ``skip_from_line``."""
from dataclasses import replace
from pathlib import Path

import pytest

from edcs.code_scanner.secret_scanner import detect_secrets_findings
from edcs.regex_engine.engine import load_rules

pytest.importorskip("detect_secrets")

RULES = load_rules(
    Path(__file__).resolve().parents[2] / "config" / "secret_rules.yaml"
)
# Enable the layer (off by default) for these tests only.
RULES_ON = replace(RULES, enable_detect_secrets_plugin=True)

# High-entropy base64-ish blob detect-secrets reliably flags.
_SECRET = "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHZlcnkgbG9uZyBzZWNyZXQ="


def _write(tmp_path):
    body = (
        f'TOKEN = "{_SECRET}"\n'          # line 1 - module body
        'def run():\n'                     # line 2
        '    return TOKEN\n'               # line 3
        'if __name__ == "__main__":\n'     # line 4 - guard
        f'    demo = "{_SECRET}"\n'        # line 5 - harness (must be skipped)
    )
    f = tmp_path / "mod.py"
    f.write_text(body, encoding="utf-8")
    return str(f)


def test_detect_secrets_disabled_by_default(tmp_path):
    f = _write(tmp_path)
    assert detect_secrets_findings("mod.py", f, RULES, skip_from_line=4) == []


def test_detect_secrets_harness_line_skipped(tmp_path):
    f = _write(tmp_path)
    found = detect_secrets_findings("mod.py", f, RULES_ON, skip_from_line=4)
    # whatever it flags, nothing at or below the guard (line 4) survives
    assert found, "expected a module-body finding"
    assert all(x.line < 4 for x in found)


def test_detect_secrets_no_cutoff_sees_harness(tmp_path):
    f = _write(tmp_path)
    with_cut = detect_secrets_findings("mod.py", f, RULES_ON, skip_from_line=4)
    no_cut = detect_secrets_findings("mod.py", f, RULES_ON, skip_from_line=None)
    # the cutoff can only remove findings, never add them
    assert len(no_cut) >= len(with_cut)
    assert any(x.line >= 4 for x in no_cut)
