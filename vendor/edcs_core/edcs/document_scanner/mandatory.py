"""Mandatory checklist matching: alias exact match then fuzzy fallback."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None


@dataclass(slots=True)
class MandatoryDoc:
    key: str
    aliases: list[str]
    weight: int
    min_chars: int = 120


@dataclass(slots=True)
class Checklist:
    docs: list[MandatoryDoc]
    fuzzy_ratio: int = 88
    boilerplate: list[str] = field(default_factory=list)
    signoff_keywords: list[str] = field(default_factory=list)

    @property
    def total_weight(self) -> int:
        return sum(d.weight for d in self.docs)


def load_checklist(path: Path) -> Checklist:
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    docs = [MandatoryDoc(key=d["key"], aliases=d.get("aliases", [d["key"]]),
                         weight=int(d.get("weight", 5)),
                         min_chars=int(d.get("min_chars", 120)))
            for d in data["mandatory"]]
    return Checklist(
        docs=docs,
        fuzzy_ratio=int(data.get("matching", {}).get("fuzzy_ratio", 88)),
        boilerplate=data.get("boilerplate_lines", []),
        signoff_keywords=data.get("signoff_keywords", []),
    )


def normalize(name: str, jira_id: str) -> str:
    stem = Path(name).stem
    stem = re.sub(re.escape(jira_id), " ", stem, flags=re.I)
    stem = re.sub(r"[_\-\.\+]+", " ", stem)
    stem = re.sub(r"\bv?\d+(\.\d+)*\b", " ", stem)      # strip version tokens
    return re.sub(r"\s+", " ", stem).strip().lower()


def match_document(doc_name: str, jira_id: str, checklist: Checklist
                   ) -> tuple[str | None, bool]:
    """Returns (mandatory_key or None, fuzzy_used)."""
    norm = normalize(doc_name, jira_id)
    for d in checklist.docs:
        for alias in d.aliases:
            if norm == alias.lower() or alias.lower() in norm:
                return d.key, False
    if fuzz:
        best_key, best_score = None, 0
        for d in checklist.docs:
            for alias in d.aliases:
                score = fuzz.token_set_ratio(norm, alias.lower())
                if score > best_score:
                    best_key, best_score = d.key, score
        if best_score >= checklist.fuzzy_ratio:
            return best_key, True
    return None, False
