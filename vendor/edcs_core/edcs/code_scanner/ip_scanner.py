"""IP scanner: broad candidate regex -> stdlib ipaddress verification ->
classification. Regexes alone over/under-match; ipaddress is ground truth."""
from __future__ import annotations

import ipaddress
import re

from edcs.models import Finding, Severity
from edcs.utils.masking import mask_line

IPV4_CAND = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
IPV6_CAND = re.compile(
    r"(?<![\w:.])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f:.%]{1,45}|::(?:[0-9A-Fa-f]{1,4}[:.]?){0,7}"
)
VERSIONISH = re.compile(r"(?i)\b(version|release|v\d|semver|chart)\b")

DOC_RANGES = [ipaddress.ip_network(n) for n in
              ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")]


def classify(ip) -> tuple[Severity, str]:
    if any(ip in net for net in DOC_RANGES):
        return Severity.INFO, "Documentation/example IP range"
    if ip.is_loopback:
        return Severity.LOW, "Loopback address hardcoded"
    if ip.is_unspecified:
        return Severity.INFO, "Unspecified/bind-all address (0.0.0.0 / ::)"
    if ip.is_multicast or ip.is_link_local or ip.is_reserved:
        return Severity.LOW, "Link-local/multicast/reserved address hardcoded"
    if getattr(ip, "is_private", False):
        return Severity.MEDIUM, "Private (RFC1918/ULA) address leaks internal topology"
    if ip.is_global:
        return Severity.HIGH, "Public IP address hardcoded"
    return Severity.LOW, "IP address hardcoded"


def scan_line(relpath: str, lineno: int, line: str) -> list[Finding]:
    findings: list[Finding] = []
    versionish = bool(VERSIONISH.search(line))
    seen: set[str] = set()

    for m in IPV4_CAND.finditer(line):
        cand = m.group(0)
        if cand in seen:
            continue
        seen.add(cand)
        try:
            ip = ipaddress.ip_address(cand)
        except ValueError:
            continue  # e.g. 2.4.10.1 as version string that fails octet range... still valid
        if cand == "255.255.255.255":
            sev, why = Severity.LOW, "Broadcast address hardcoded"
        else:
            sev, why = classify(ip)
        if versionish and sev.rank >= Severity.MEDIUM.rank:
            sev, why = Severity.INFO, why + " (version-like context - downgraded)"
        findings.append(Finding(sev, "IPV4", relpath, why,
                                "Move IPs to configuration/DNS; never hardcode.",
                                "EDCS-IP-001", lineno, mask_line(line, "")))

    for m in IPV6_CAND.finditer(line):
        cand = m.group(0).split("%")[0].rstrip(":.")
        if not cand or cand in seen or ":" not in cand:
            continue
        seen.add(cand)
        try:
            ip = ipaddress.ip_address(cand)
        except ValueError:
            continue
        sev, why = classify(ip)
        why = why.replace("IP address", "IPv6 address")
        if versionish and sev.rank >= Severity.MEDIUM.rank:
            sev = Severity.INFO
        findings.append(Finding(sev, "IPV6", relpath, why,
                                "Move IPs to configuration/DNS; never hardcode.",
                                "EDCS-IP-002", lineno, mask_line(line, "")))
    return findings
