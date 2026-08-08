"""Weighted-earned compliance scoring with explainable hard caps.

score = 100 * (weight of mandatory docs present AND valid) / total weight
caps: folder missing -> 0 | blank/corrupt mandatory -> 40 |
      missing weight>=10 -> 70 | missing weight<10 -> 85 | naming only -> 95
Every cap that fires is returned with a reason - auditability is the point.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from edcs.document_scanner.mandatory import Checklist


@dataclass(slots=True)
class DocState:
    key: str
    weight: int
    present: bool = False
    named_ok: bool = True
    blank: bool = False
    corrupt: bool = False
    protected: bool = False


@dataclass(slots=True)
class ScoreResult:
    score: int
    caps_applied: list[str] = field(default_factory=list)


def compute_score(states: list[DocState], checklist: Checklist,
                  folder_missing: bool = False) -> ScoreResult:
    if folder_missing:
        return ScoreResult(0, ["Score = 0: ERIDOC folder for the Jira ID is missing"])

    total = checklist.total_weight or 1
    # naming problems cap the score (below) but do not erase earned weight
    earned = sum(s.weight for s in states
                 if s.present and not (s.blank or s.corrupt or s.protected))
    score = round(100 * earned / total)
    caps: list[str] = []

    def cap(value: int, reason: str):
        nonlocal score
        if score > value:
            score = value
        caps.append(reason)

    for s in states:
        if s.present and (s.blank or s.corrupt):
            cap(40, f"Capped at 40: mandatory document '{s.key}' is "
                    f"{'blank' if s.blank else 'corrupt'}")
    for s in states:
        if not s.present:
            if s.weight >= 10:
                cap(70, f"Capped at 70: mandatory document '{s.key}' (weight {s.weight}) missing")
            else:
                cap(85, f"Capped at 85: mandatory document '{s.key}' (weight {s.weight}) missing")
    if not caps and any(not s.named_ok for s in states):
        cap(95, "Capped at 95: naming violations on mandatory documents")
    return ScoreResult(max(0, min(100, score)), caps)
