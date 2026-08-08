"""Key-aware credential scan of structured config formats.

Line regexes miss 'password:' nested three levels deep - so YAML/JSON/INI/
XML/Terraform are parsed and keys walked. Kubernetes Secret manifests with
inline data are flagged CRITICAL."""
from __future__ import annotations

import configparser
import json
import logging
from pathlib import Path

from ruamel.yaml import YAML

from edcs.models import Finding, Severity
from edcs.regex_engine.engine import RuleSet
from edcs.utils.masking import mask_secret

try:
    import defusedxml.ElementTree as SafeET  # XXE / billion-laughs protection
except ImportError:  # pragma: no cover
    SafeET = None

log = logging.getLogger(__name__)


def _is_cred_key(key: str, cred_keys: list[str]) -> bool:
    k = str(key).lower()
    return any(c in k for c in cred_keys)


def _finding(relpath: str, key: str, value: str, line: int | None,
             rs: RuleSet) -> Finding | None:
    v = str(value).strip()
    if not v or len(v) < 4 or v.startswith(("${", "{{", "%(", "<")):
        return None
    sev = Severity.INFO if rs.is_placeholder(v) else Severity.CRITICAL
    return Finding(sev, "CONFIG_CRED", relpath,
                   f"Credential key '{key}' holds a literal value in configuration",
                   "Reference a secret store / env injection instead of a literal.",
                   "EDCS-CFG-001", line, f"{key}={mask_secret(v)}")


def _walk(node, relpath: str, rs: RuleSet, out: list[Finding], line_of=None):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (str, int)) and _is_cred_key(k, rs.config_credential_keys):
                ln = line_of(node, k) if line_of else None
                f = _finding(relpath, str(k), str(v), ln, rs)
                if f:
                    out.append(f)
            else:
                _walk(v, relpath, rs, out, line_of)
    elif isinstance(node, list):
        for item in node:
            _walk(item, relpath, rs, out, line_of)


def scan_config_file(path: Path, relpath: str, rs: RuleSet) -> list[Finding]:
    out: list[Finding] = []
    ext = path.suffix.lower()
    try:
        if ext in (".yml", ".yaml"):
            yaml = YAML(typ="rt")  # round-trip keeps line numbers (.lc)
            for doc in yaml.load_all(path.read_text(encoding="utf-8", errors="replace")):
                if doc is None:
                    continue
                def line_of(node, key):
                    try:
                        return node.lc.data[key][0] + 1
                    except Exception:
                        return None
                # Kubernetes Secret with inline data
                if isinstance(doc, dict) and str(doc.get("kind", "")).lower() == "secret":
                    if doc.get("data") or doc.get("stringData"):
                        out.append(Finding(
                            Severity.CRITICAL, "CONFIG_CRED", relpath,
                            "Kubernetes Secret manifest with inline data committed to repo",
                            "Use sealed-secrets/external-secrets; never commit Secret data.",
                            "EDCS-CFG-002", None, "kind: Secret (data present)"))
                _walk(doc, relpath, rs, out, line_of)
        elif ext == ".json":
            _walk(json.loads(path.read_text(encoding="utf-8", errors="replace")),
                  relpath, rs, out)
        elif ext in (".ini", ".cfg", ".conf", ".properties"):
            cp = configparser.ConfigParser(strict=False, interpolation=None)
            try:
                cp.read_string(path.read_text(encoding="utf-8", errors="replace"))
                for section in cp.sections():
                    for k, v in cp.items(section):
                        if _is_cred_key(k, rs.config_credential_keys):
                            f = _finding(relpath, k, v, None, rs)
                            if f:
                                out.append(f)
            except configparser.Error:
                pass  # .properties without sections etc. - line rules still apply
        elif ext == ".xml" and SafeET is not None:
            root = SafeET.parse(str(path)).getroot()
            for el in root.iter():
                if _is_cred_key(el.tag, rs.config_credential_keys) and (el.text or "").strip():
                    f = _finding(relpath, el.tag, el.text, None, rs)
                    if f:
                        out.append(f)
                for k, v in el.attrib.items():
                    if _is_cred_key(k, rs.config_credential_keys):
                        f = _finding(relpath, k, v, None, rs)
                        if f:
                            out.append(f)
        elif ext in (".tf", ".tfvars"):
            try:
                import hcl2
                data = hcl2.loads(path.read_text(encoding="utf-8", errors="replace"))
                _walk(data, relpath, rs, out)
            except Exception:
                pass  # HCL parse failure - line rules still apply
    except Exception as e:
        log.debug("Config scan skipped %s: %s", relpath, e)
    return out
