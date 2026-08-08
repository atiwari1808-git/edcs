"""Bitbucket code scanner adapter — wired to the real EDCS v1.0.1
CodeScanner (vendor/edcs_core). See README.md "Integration" section.

Host allow-listing reuses EDCS's own validate_repo_url() (same
BITBUCKET_ALLOWED_HOSTS the vendored clone client itself enforces) so
there is exactly one place that decides which hosts are trusted.

severity >= fail_threshold (default HIGH)  -> failed_checks
severity <  fail_threshold                  -> warnings
Each item keeps EDCS's `recommendation` text for the "suggest correction"
step.
"""
import time
from django.conf import settings as dj
from .base import ScanResult, TransientScannerError

NAME = "BITBUCKET"


def validate_repo_url(url: str) -> bool:
    if dj.DEMO_MODE:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        return any(h == host or host.endswith("." + h) or h in host
                   for h in ("bitbucket.org", "bitbucket"))
    from edcs.config import get_settings
    from edcs.bitbucket_client.client import validate_repo_url as edcs_validate
    from edcs.exceptions import SecurityError
    s = get_settings()
    try:
        edcs_validate(url, s.allowed_hosts)
        return True
    except SecurityError:
        return False


def run(repo_url: str) -> ScanResult:
    return _run_demo(repo_url) if dj.DEMO_MODE else _run_real(repo_url)


def _finding_to_item(f):
    return {
        "code": f.rule_id, "title": f.category.replace("_", " ").title(),
        "category": f.category,
        "detail": f.reason, "recommendation": f.recommendation,
        "severity": f.severity.value, "file": f.file,
        "line": f.line,                 # real line number, e.g. 1035
        "content": f.matched_text or "",  # the actual (masked-if-secret) source line
    }


def _run_real(repo_url: str) -> ScanResult:
    from edcs.config import get_settings
    from edcs.code_scanner.scanner import CodeScanner
    from edcs.exceptions import CloneError, SecurityError

    s = get_settings()
    stats: dict = {}
    try:
        findings = CodeScanner(s).scan(repo_url, stats)
    except CloneError as e:
        # disk space / clone timeout / transient git failure -> retry the task
        raise TransientScannerError(str(e)) from e
    except SecurityError:
        raise   # bad host / scheme -> terminal, never a false PASS

    r = ScanResult()
    for f in findings:
        item = _finding_to_item(f)
        if f.severity.rank >= s.fail_threshold.rank:
            r.failed_checks.append(item)
        else:
            r.warnings.append(item)

    if not r.failed_checks:
        r.passed_checks.append({
            "code": "BB-CLEAN", "title": "No blocking issues found",
            "detail": f"{stats.get('code_files_scanned', 0)} files scanned, "
                      f"{len(findings)} total findings (below fail threshold "
                      f"{s.severity_fail_threshold}).",
            "recommendation": "", "severity": "INFO", "file": "",
            "category": "CLEAN", "line": None, "content": "",
        })
    r.status = "FAILED" if r.failed_checks else "PASSED"
    r.stats = {
        "files_scanned": stats.get("code_files_scanned", 0),
        "total_findings": len(findings),
    }
    return r


def _run_demo(repo_url: str) -> ScanResult:
    time.sleep(1.0)
    r = ScanResult()
    r.passed_checks = [
        {"code": "BB-001", "title": "Branch protection enabled", "detail": "main is protected",
         "recommendation": "", "severity": "INFO", "file": "", "category": "INFO",
         "line": None, "content": ""},
    ]
    if "fail" in repo_url.lower():
        r.failed_checks = [
            {"code": "EDCS-SCAN-010", "title": "Secret", "file": "config/settings.py",
             "detail": "Hardcoded API key pattern detected", "category": "SECRET",
             "recommendation": "Move the credential to a secrets manager / environment "
                               "variable and rotate the exposed key.",
             "severity": "CRITICAL", "line": 42, "content": "API_KEY = 'ab************yz'"},
            {"code": "EDCS-IP-001", "title": "Hardcoded Ipv4 Address",
             "file": "ace_core_huawei_local_changes_input_handler.py", "category": "IPV4",
             "detail": "Private (RFC1918/ULA) address leaks internal topology",
             "recommendation": "Move IPs to configuration/DNS; never hardcode.",
             "severity": "HIGH", "line": 1035, "content": "'node_ip': '150.236.17.51',"},
            {"code": "EDCS-IP-001", "title": "Hardcoded Ipv4 Address",
             "file": "ace_core_huawei_local_changes_input_handler.py", "category": "IPV4",
             "detail": "Private (RFC1918/ULA) address leaks internal topology",
             "recommendation": "Move IPs to configuration/DNS; never hardcode.",
             "severity": "HIGH", "line": 1037, "content": "'oss_ip': '150.236.17.51',"},
        ]
    stats = {"code_files_scanned": 70, "total_findings": len(r.failed_checks)}
    r.stats = stats
    if not r.failed_checks:
        r.passed_checks.append({
            "code": "BB-CLEAN", "title": "No blocking issues found",
            "detail": f"{stats['code_files_scanned']} files scanned, 0 total findings.",
            "recommendation": "", "severity": "INFO", "file": "",
            "category": "CLEAN", "line": None, "content": "",
        })
    return r.finalize_status()
