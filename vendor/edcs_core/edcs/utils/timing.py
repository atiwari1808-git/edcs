from __future__ import annotations

import time
from contextlib import contextmanager


@contextmanager
def timed(stats: dict, key: str):
    t0 = time.monotonic()
    try:
        yield
    finally:
        stats[key] = round(time.monotonic() - t0, 2)
