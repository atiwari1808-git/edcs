"""Durable SQLite-backed job queue with lease-based crash recovery.

- Message-ID UNIQUE constraint gives email idempotency for free.
- Workers lease jobs; a crashed worker's lease expires and another worker
  re-leases the job (re-scan is safe: the whole pipeline is idempotent).
- Swap for Redis/rq later behind the same interface (see design §7.5)."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from edcs.models import ScanJob

LEASE_SECONDS = 3600
MAX_ATTEMPTS = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    job_id TEXT PRIMARY KEY,
    message_id TEXT UNIQUE,
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',   -- queued|leased|done|failed
    attempts INTEGER NOT NULL DEFAULT 0,
    leased_until REAL,
    created REAL NOT NULL
);
"""


class JobQueue:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=30, isolation_level=None,
                                    check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(_SCHEMA)

    def enqueue(self, job: ScanJob) -> bool:
        """Returns False if the mail was already processed (idempotency)."""
        payload = json.dumps({**asdict(job), "received_at": job.received_at.isoformat()})
        try:
            self.conn.execute(
                "INSERT INTO queue(job_id, message_id, payload, created) VALUES(?,?,?,?)",
                (job.job_id, job.message_id or job.job_id, payload, time.time()))
            return True
        except sqlite3.IntegrityError:
            return False

    def lease(self) -> ScanJob | None:
        now = time.time()
        row = self.conn.execute(
            "SELECT job_id, payload FROM queue WHERE "
            "(state='queued' OR (state='leased' AND leased_until < ?)) "
            "AND attempts < ? ORDER BY created LIMIT 1", (now, MAX_ATTEMPTS)).fetchone()
        if not row:
            return None
        job_id, payload = row
        cur = self.conn.execute(
            "UPDATE queue SET state='leased', leased_until=?, attempts=attempts+1 "
            "WHERE job_id=? AND (state='queued' OR leased_until < ?)",
            (now + LEASE_SECONDS, job_id, now))
        if cur.rowcount == 0:
            return None  # lost the race to another worker
        d = json.loads(payload)
        d.pop("received_at", None)
        return ScanJob(**d)

    def complete(self, job_id: str, ok: bool) -> None:
        self.conn.execute("UPDATE queue SET state=? WHERE job_id=?",
                          ("done" if ok else "failed", job_id))
