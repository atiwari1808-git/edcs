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


def test_commented_password_not_flagged():
    # whole-line comment -> secret scanner skips it entirely
    assert _scan('# password = "SuperSecret123"') == []


def test_commented_slash_secret_not_flagged():
    assert _scan('// token = "abcd1234efgh"') == []


def test_sql_password_column_reference_downgraded():
    # `WHERE password = <variable/column>` is a DB reference, not a literal
    f = _scan("WHERE password = hashed_input")
    assert f and all(x.severity == Severity.INFO for x in f)


def test_set_password_variable_reference_downgraded():
    f = _scan("SET password = new_hashed_value")
    assert f and all(x.severity == Severity.INFO for x in f)


def test_dotted_password_reference_downgraded():
    f = _scan("AND user.password = computed_hash")
    assert f and all(x.severity == Severity.INFO for x in f)


def test_real_hardcoded_password_still_critical():
    # quoted literal must remain a real finding (regression guard)
    f = _scan('password = "SuperSecret123"')
    assert any(x.severity == Severity.CRITICAL for x in f)


def test_db_connect_passwd_attribute_reference_downgraded():
    # passwd=app.DB_PASS is an attribute reference passed to a connect() call
    line = ("dbc123 = MySQLdb.connect(host=app.DB_HOST, user=app.DB_USER, "
            "passwd=app.DB_PASS, db=app.DB_NAME)")
    f = _scan(line)
    assert f and all(x.severity == Severity.INFO for x in f)


def test_password_assigned_function_call_downgraded():
    # value is a function-call expression, not a literal credential
    f = _scan("password = base64.b64decode(data[0][1])")
    assert f and all(x.severity == Severity.INFO for x in f)


def test_password_assigned_getenv_downgraded():
    f = _scan("password = os.environ['DB_PASSWORD']")
    assert f and all(x.severity == Severity.INFO for x in f)
