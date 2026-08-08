from pathlib import Path

from edcs.code_scanner.secret_scanner import scan_lines
from edcs.models import Severity
from edcs.regex_engine.engine import load_rules

RULES = load_rules(Path(__file__).resolve().parents[2] / "config" / "secret_rules.yaml")


def _scan(line, path="app/main.py"):
    return scan_lines(path, [line], RULES)


def test_hardcoded_password_critical():
    f = _scan('password = "SuperSecret123"')
    assert any(x.severity == Severity.CRITICAL for x in f)


def test_placeholder_downgraded_to_info():
    f = _scan('password = "changeme"')
    assert f and all(x.severity == Severity.INFO for x in f)


def test_env_reference_not_flagged():
    f = _scan('password = "${DB_PASSWORD}"')
    assert not [x for x in f if x.severity.rank >= Severity.HIGH.rank]


def test_private_key_block():
    f = _scan("-----BEGIN RSA PRIVATE KEY-----")
    assert any(x.rule_id == "EDCS-SEC-002" for x in f)


def test_connection_string():
    f = _scan("db = mysql://root:hunter2@10.0.0.5/prod")
    assert any(x.rule_id == "EDCS-SEC-005" for x in f)


def test_test_path_downgraded():
    prod = _scan('token = "abcd1234efgh"')
    test = _scan('token = "abcd1234efgh"', path="tests/test_x.py")
    assert max(x.severity.rank for x in prod) > max(x.severity.rank for x in test)


def test_secret_is_masked_in_output():
    f = _scan('password = "SuperSecret123"')
    assert all("SuperSecret123" not in x.matched_text for x in f)
