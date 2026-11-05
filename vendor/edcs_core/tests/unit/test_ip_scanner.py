from edcs.code_scanner.ip_scanner import scan_line
from edcs.models import Severity


def _sev(findings, cat):
    return [f.severity for f in findings if f.category == cat]


def test_private_ipv4_medium():
    f = scan_line("a.py", 1, 'HOST = "10.221.13.5"')
    assert Severity.MEDIUM in _sev(f, "IPV4")


def test_public_ipv4_high():
    f = scan_line("a.py", 1, "curl http://8.8.8.8/x")
    assert Severity.HIGH in _sev(f, "IPV4")


def test_loopback_low():
    f = scan_line("a.py", 1, "bind 127.0.0.1")
    assert Severity.LOW in _sev(f, "IPV4")


def test_version_string_not_flagged_high():
    f = scan_line("a.py", 1, "chart version 2.4.10.1 release")
    assert all(x == Severity.INFO for x in _sev(f, "IPV4"))


def test_invalid_octets_discarded():
    f = scan_line("a.py", 1, "x = 999.999.999.999")
    assert not f


def test_ipv6_compressed():
    f = scan_line("a.py", 1, "addr = fd00::1")
    assert _sev(f, "IPV6")


def test_ipv6_loopback():
    f = scan_line("a.py", 1, "ping ::1")
    assert _sev(f, "IPV6")


def test_commented_hash_ip_not_flagged():
    assert scan_line("a.py", 1, "# HOST = 8.8.8.8") == []


def test_commented_slash_ip_not_flagged():
    assert scan_line("a.js", 1, "// const ip = '10.0.0.5'") == []


def test_commented_sql_dash_ip_not_flagged():
    assert scan_line("a.sql", 1, "-- server 203.0.113.9") == []


def test_inline_comment_ip_still_flagged():
    # code precedes the comment -> real config, must still be detected
    f = scan_line("a.py", 1, "HOST = '8.8.8.8'  # google dns")
    assert Severity.HIGH in _sev(f, "IPV4")
