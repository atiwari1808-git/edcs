"""Safe Bitbucket clone lifecycle.

- HTTPS-only host allowlist (the URL comes from an email: SSRF guard)
- shallow, single-branch, blob-size-filtered clone
- credentials via GIT_ASKPASS environment - never argv, never on disk
- guaranteed deletion via context manager + startup janitor for crashes
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from git import GitCommandError, Repo

from edcs.config import Settings
from edcs.exceptions import CloneError, SecurityError
from edcs.utils.fs import force_rw_then_delete, free_mb

import shutil

log = logging.getLogger(__name__)

_BROWSE_RE = re.compile(r"/projects/(?P<proj>[^/]+)/repos/(?P<repo>[^/?#]+)", re.I)


def validate_repo_url(url: str, allowed_hosts: set[str]) -> str:
    p = urlparse(url.strip())
    if p.scheme != "https":
        raise SecurityError(f"Only https clone URLs allowed, got: {p.scheme}")
    if (p.hostname or "").lower() not in allowed_hosts:
        raise SecurityError(f"Repository host not allowlisted: {p.hostname}")
    return url.strip()


def to_clone_url(url: str) -> str:
    """Rewrite Bitbucket browse URL -> canonical clone URL if needed."""
    p = urlparse(url)
    m = _BROWSE_RE.search(p.path)
    if m:
        return f"https://{p.hostname}/scm/{m.group('proj').lower()}/{m.group('repo')}.git"
    return url if url.endswith(".git") else url + ".git"


class ClonedRepo:
    """with ClonedRepo(url, settings) as path: ...   -> path is deleted after."""

    def __init__(self, url: str, s: Settings):
        self.url = to_clone_url(validate_repo_url(url, s.allowed_hosts))
        self.s = s
        self.dir: str | None = None

    def __enter__(self) -> Path:
        if free_mb(self.s.clone_dir) < self.s.max_repo_mb:
            raise CloneError("Insufficient disk space for clone - aborting cleanly")
        self.dir = tempfile.mkdtemp(prefix="edcs_", dir=self.s.clone_dir)
        os.chmod(self.dir, 0o700)
        helper = "git-askpass.bat" if os.name == "nt" else "git-askpass"
        askpass = str(Path(__file__).resolve().parents[2] / "bin" / helper)
        env = {
            "GIT_ASKPASS": askpass,
            "EDCS_GIT_USER": self.s.bitbucket_username,
            "EDCS_GIT_TOKEN": self.s.bitbucket_token.get_secret_value(),
            "GIT_TERMINAL_PROMPT": "0",
        }
        try:
            Repo.clone_from(
                self.url, self.dir, env=env,
                depth=self.s.clone_depth, single_branch=True,
                multi_options=[f"--filter=blob:limit={self.s.max_file_mb}m"],
            )
        except GitCommandError as e:
            self._cleanup()
            # GitPython includes the command line in the message - mask defensively
            raise CloneError(f"git clone failed: {str(e)[:300]}") from None
        log.info("Cloned %s", self.url)
        return Path(self.dir)

    def __exit__(self, *exc) -> bool:
        self._cleanup()
        return False

    def _cleanup(self) -> None:
        if self.dir and os.path.isdir(self.dir):
            shutil.rmtree(self.dir, onerror=force_rw_then_delete)
            log.info("Deleted temporary clone workspace")
        self.dir = None
