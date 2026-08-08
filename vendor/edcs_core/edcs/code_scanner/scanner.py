"""Code scan orchestration: safe clone -> file walk -> parallel scan.

- symlinks never followed; every path must resolve inside the clone root
- binary/oversize files skipped
- ProcessPoolExecutor for CPU-bound regex work
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from edcs.bitbucket_client.client import ClonedRepo
from edcs.code_scanner import config_scanner, ip_scanner, secret_scanner
from edcs.config import Settings, get_settings
from edcs.models import Finding, Severity
from edcs.regex_engine.engine import RuleSet, load_rules
from edcs.utils.fs import is_within, looks_binary

log = logging.getLogger(__name__)

SPECIAL_NAMES = ("dockerfile", "jenkinsfile", "makefile", ".env", "id_rsa", "id_ed25519")
CONFIG_EXTS = {".yml", ".yaml", ".json", ".ini", ".cfg", ".conf", ".properties",
               ".xml", ".tf", ".tfvars"}


def _wanted(path: Path, allowed_ext: set[str]) -> bool:
    name = path.name.lower()
    if any(name.startswith(sn) or name == sn for sn in SPECIAL_NAMES):
        return True
    return path.suffix.lower() in allowed_ext


def collect_files(root: Path, s: Settings) -> tuple[list[Path], list[Finding]]:
    files: list[Path] = []
    findings: list[Finding] = []
    max_bytes = s.max_file_mb * 1024 * 1024
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in s.excluded_dir_set]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.is_symlink() or not is_within(root, p):
                continue  # symlink-escape guard
            if not _wanted(p, s.allowed_ext_set):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            rel = str(p.relative_to(root))
            if size > max_bytes:
                findings.append(Finding(
                    Severity.INFO, "FILE_OVERSIZE", rel,
                    f"File exceeds {s.max_file_mb} MB and was skipped",
                    "Large files in source control are a smell; review manually.",
                    "EDCS-SCAN-002"))
                continue
            if size == 0 or looks_binary(p):
                continue
            files.append(p)
    return files, findings


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        # lossless byte->char so secrets in odd encodings aren't invisible
        return path.read_text(encoding="latin-1", errors="replace").splitlines()


def scan_one_file(abspath: str, root: str, rules_file: str) -> list[Finding]:
    """Worker-process entry point (must be importable/picklable)."""
    rs = _rules_cached(rules_file)
    p, rootp = Path(abspath), Path(root)
    rel = str(p.relative_to(rootp))
    lines = _read_lines(p)
    findings = secret_scanner.scan_lines(rel, lines, rs)
    for lineno, line in enumerate(lines, start=1):
        findings.extend(ip_scanner.scan_line(rel, lineno, line))
    if p.suffix.lower() in CONFIG_EXTS:
        findings.extend(config_scanner.scan_config_file(p, rel, rs))
    findings.extend(secret_scanner.detect_secrets_findings(rel, abspath, rs))
    return secret_scanner.dedupe(findings)


_RS_CACHE: dict[str, RuleSet] = {}


def _rules_cached(rules_file: str) -> RuleSet:
    if rules_file not in _RS_CACHE:
        _RS_CACHE[rules_file] = load_rules(Path(rules_file))
    return _RS_CACHE[rules_file]


class CodeScanner:
    def __init__(self, s: Settings | None = None):
        self.s = s or get_settings()
        # fail fast: rules must compile at boot
        load_rules(self.s.secret_rules_file)

    def scan(self, repo_url: str, stats: dict) -> list[Finding]:
        findings: list[Finding] = []
        with ClonedRepo(repo_url, self.s) as root:
            files, walk_findings = collect_files(root, self.s)
            findings.extend(walk_findings)
            stats["code_files_scanned"] = len(files)
            log.info("Scanning %d files with %d workers", len(files), self.s.workers)
            rules_file = str(self.s.secret_rules_file.resolve())
            if len(files) < 20 or self.s.workers <= 1:
                for f in files:
                    findings.extend(scan_one_file(str(f), str(root), rules_file))
            else:
                with ProcessPoolExecutor(max_workers=self.s.workers) as pool:
                    futs = {pool.submit(scan_one_file, str(f), str(root), rules_file): f
                            for f in files}
                    for fut in as_completed(futs):
                        try:
                            findings.extend(fut.result())
                        except Exception as e:  # per-item isolation
                            rel = str(futs[fut].relative_to(root))
                            log.warning("Scan failed for %s: %s", rel, e)
                            findings.append(Finding(
                                Severity.INFO, "SCAN_ERROR", rel,
                                f"File could not be scanned: {type(e).__name__}",
                                "Review the file manually.", "EDCS-SCAN-003"))
        stats["code_findings"] = len(findings)
        return findings
