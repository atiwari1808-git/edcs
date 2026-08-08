"""Structured logging with per-job context and per-job log files.

- Global rotating log: LOG_DIR/edcs.log (JSON lines)
- Per-job log:        LOG_DIR/jobs/<jira>_<job_id>.log (attached to report mail)
- job_id/jira_id injected on every record via contextvars.
- A masking filter is the last-line defence against secrets in logs.
"""
from __future__ import annotations

import contextvars
import logging
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from pythonjsonlogger import jsonlogger

_job_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("edcs_job", default={})

_SECRETISH = re.compile(
    r"(?i)\b(password|passwd|token|secret|apikey|api_key|authorization)\b\s*[:=]\s*\S+"
)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _job_ctx.get()
        record.job_id = ctx.get("job_id", "-")
        record.jira_id = ctx.get("jira_id", "-")
        if isinstance(record.msg, str):
            record.msg = _SECRETISH.sub(r"\1=********", record.msg)
        return True


def set_job_context(job_id: str, jira_id: str) -> None:
    _job_ctx.set({"job_id": job_id, "jira_id": jira_id})


def clear_job_context() -> None:
    _job_ctx.set({})


def setup(log_dir: Path, level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:  # idempotent
        return
    root.setLevel(level.upper())
    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(job_id)s %(jira_id)s %(message)s"
    )
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(jira_id)s/%(job_id)s] %(name)s: %(message)s"))
    console.addFilter(ContextFilter())
    root.addHandler(console)

    log_dir.mkdir(parents=True, exist_ok=True)
    fh = TimedRotatingFileHandler(log_dir / "edcs.log", when="midnight", backupCount=14)
    fh.setFormatter(fmt)
    fh.addFilter(ContextFilter())
    root.addHandler(fh)


def job_log_file(log_dir: Path, jira_id: str, job_id: str) -> tuple[logging.Handler, Path]:
    """Attach a per-job file handler; caller must remove it when the job ends."""
    jobs_dir = log_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    path = jobs_dir / f"{jira_id}_{job_id}.log"
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    h.addFilter(ContextFilter())
    logging.getLogger().addHandler(h)
    return h, path
