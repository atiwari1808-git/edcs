"""Shannon entropy detector for generic high-entropy secrets (base64/hex)."""
from __future__ import annotations

import math
import re
from collections import Counter

B64_RE = re.compile(r"[A-Za-z0-9+/=]{20,}")
HEX_RE = re.compile(r"\b[0-9a-fA-F]{24,}\b")


def shannon(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def high_entropy_candidates(line: str, cfg: dict) -> list[str]:
    out = []
    b64_t = float(cfg.get("base64_threshold", 4.5))
    b64_min = int(cfg.get("base64_min_len", 20))
    hex_t = float(cfg.get("hex_threshold", 3.0))
    hex_min = int(cfg.get("hex_min_len", 24))
    for m in B64_RE.findall(line):
        if len(m) >= b64_min and shannon(m) >= b64_t:
            out.append(m)
    for m in HEX_RE.findall(line):
        if len(m) >= hex_min and shannon(m) >= hex_t:
            out.append(m)
    return out
