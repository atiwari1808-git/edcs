from pathlib import Path

from edcs.code_scanner.comments import main_guard_lineno
from edcs.code_scanner.scanner import scan_one_file

RULES_FILE = str(
    Path(__file__).resolve().parents[2] / "config" / "secret_rules.yaml"
)


def test_main_guard_lineno_found():
    lines = [
        "import os",
        "def f():",
        "    return 1",
        'if __name__ == "__main__":',
        "    print(f())",
    ]
    assert main_guard_lineno(lines) == 4


def test_main_guard_lineno_single_quotes_and_spacing():
    assert main_guard_lineno(["if __name__=='__main__':"]) == 1


def test_main_guard_lineno_absent():
    assert main_guard_lineno(["x = 1", "y = 2"]) is None


def test_main_guard_not_matched_when_indented():
    # a nested/quoted occurrence must not be treated as the module guard
    assert main_guard_lineno(["    if __name__ == '__main__':"]) is None


def _scan(tmp_path, body):
    f = tmp_path / "mod.py"
    f.write_text(body, encoding="utf-8")
    return scan_one_file(str(f), str(tmp_path), RULES_FILE)


def test_secret_in_main_block_excluded(tmp_path):
    body = (
        "import os\n"
        "def run():\n"
        "    return os.getenv('X')\n"
        'if __name__ == "__main__":\n'
        '    password = "SuperSecret123"\n'
        "    host = '8.8.8.8'\n"
    )
    findings = _scan(tmp_path, body)
    # nothing from the demo/test-run harness should be reported
    assert findings == []


def test_secret_above_main_block_still_flagged(tmp_path):
    body = (
        'API_KEY = "sk-live-abcd1234efgh"\n'
        'if __name__ == "__main__":\n'
        '    password = "SuperSecret123"\n'
    )
    findings = _scan(tmp_path, body)
    # real credential in module body is still caught; harness one is not
    assert findings, "module-level secret should still be flagged"
    assert all(f.line == 1 for f in findings)


def test_file_without_guard_unaffected(tmp_path):
    body = 'password = "SuperSecret123"\n'
    findings = _scan(tmp_path, body)
    assert any(f.severity.name == "CRITICAL" for f in findings)
