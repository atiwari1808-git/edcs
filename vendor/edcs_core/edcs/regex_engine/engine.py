"""Compiled secret ruleset with timeouts and allowlists.

Uses the `regex` package (supports match timeouts - stdlib `re` doesn't):
protection against catastrophic backtracking on pathological files.
A pattern that fails to compile aborts boot (fail fast)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import regex
from ruamel.yaml import YAML

from edcs.exceptions import ConfigError
from edcs.models import Severity

FILE_SCAN_TIMEOUT_S = 5.0


@dataclass(slots=True)
class Rule:
    id: str
    name: str
    pattern: "regex.Pattern"
    severity: Severity
    reason: str
    recommendation: str


@dataclass(slots=True)
class RuleSet:
    rules: list[Rule]
    allowlist_values: list["regex.Pattern"]
    allowlist_paths: list[str]
    entropy_cfg: dict = field(default_factory=dict)
    config_credential_keys: list[str] = field(default_factory=list)
    # Yelp detect-secrets plugin layer (rule EDCS-DS-001). OFF by default:
    # it runs with hardcoded settings that ignore this YAML and fires on long
    # file paths / numeric node IDs (high entropy but not secrets). The named
    # EDCS-SEC-00x regex rules already cover real credentials. Set
    # `enable_detect_secrets_plugin: true` in secret_rules.yaml to re-enable.
    enable_detect_secrets_plugin: bool = False

    def is_placeholder(self, value: str) -> bool:
        return any(p.match(value.strip().strip("\"'")) for p in self.allowlist_values)

    def path_downgraded(self, relpath: str) -> bool:
        rel = relpath.replace("\\", "/")
        return any(seg in rel for seg in self.allowlist_paths)


def load_rules(path: Path) -> RuleSet:
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    rules: list[Rule] = []
    for r in data.get("rules", []):
        if r.get("engine") == "entropy":
            continue  # handled by entropy module
        try:
            pat = regex.compile(r["pattern"])
        except regex.error as e:
            raise ConfigError(f"Rule {r.get('id')} pattern does not compile: {e}") from None
        rules.append(Rule(
            id=r["id"], name=r.get("name", r["id"]), pattern=pat,
            severity=Severity(r.get("severity", "MEDIUM")),
            reason=r.get("reason", r.get("name", "Pattern matched")),
            recommendation=r.get("recommendation",
                                 "Remove the hardcoded value; inject at runtime.")))
    allow_vals = [regex.compile(p) for p in data.get("allowlist_values", [])]
    return RuleSet(
        rules=rules,
        allowlist_values=allow_vals,
        allowlist_paths=data.get("allowlist_paths", []),
        entropy_cfg=data.get("entropy", {}),
        config_credential_keys=data.get("config_credential_keys", []),
        enable_detect_secrets_plugin=bool(
            data.get("enable_detect_secrets_plugin", False)),
    )


def downgrade(sev: Severity) -> Severity:
    order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
    idx = order.index(sev)
    return order[max(0, idx - 1)]
