"""Extractor Strategy registry: one extractor per file family.

Each extractor returns ExtractionResult; parser exceptions become findings,
never crashes (per-item isolation)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class ExtractionResult:
    text: str = ""
    page_count: int = 0
    image_only_pages: int = 0
    text_pages: int = 0
    cell_count: int = 0            # spreadsheets
    error: str = ""                # parser exception -> DOC_CORRUPT
    protected: bool = False        # password protected
    extra: dict = field(default_factory=dict)


_REGISTRY: dict[str, Callable[[Path], ExtractionResult]] = {}


def register(*extensions: str):
    def deco(fn):
        for ext in extensions:
            _REGISTRY[ext.lower()] = fn
        return fn
    return deco


def get_extractor(path: Path):
    return _REGISTRY.get(path.suffix.lower())


def supported_extensions() -> set[str]:
    return set(_REGISTRY)
