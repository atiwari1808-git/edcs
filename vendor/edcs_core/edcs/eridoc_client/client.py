"""ERIDOC d2rest facade: Basic Auth session, tenacity retries, DQL paging,
streamed content download with a size cap."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from edcs.config import Settings
from edcs.exceptions import EridocError

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, EridocError):
        return exc.retryable
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


class EridocClient:
    def __init__(self, s: Settings):
        self.base = f"{str(s.eridoc_rest_url).rstrip('/')}/repositories/{s.eridoc_repository}"
        self.timeout = s.eridoc_timeout_s
        self.max_doc_bytes = s.eridoc_max_doc_mb * 1024 * 1024
        self.sess = requests.Session()
        self.sess.auth = (s.eridoc_username, s.eridoc_password.get_secret_value())
        self.sess.verify = s.eridoc_ca_bundle or s.eridoc_verify_tls
        self.sess.headers["Accept"] = "application/json"
        self.sess.mount("https://", HTTPAdapter(pool_maxsize=10))

    # -- low level --------------------------------------------------------
    @retry(stop=stop_after_attempt(4),
           wait=wait_exponential_jitter(initial=2, max=30),
           retry=retry_if_exception(_is_retryable), reraise=True)
    def _get(self, url: str, **kw) -> requests.Response:
        r = self.sess.get(url, timeout=self.timeout, **kw)
        if r.status_code in RETRYABLE_STATUS:
            raise EridocError(f"ERIDOC {r.status_code} on {url}", retryable=True)
        if r.status_code in (401, 403):
            raise EridocError(f"ERIDOC auth failure {r.status_code} - check credentials",
                              retryable=False)
        r.raise_for_status()
        return r

    # -- DQL with paging ---------------------------------------------------
    def dql(self, query: str) -> list[dict]:
        out: list[dict] = []
        page = f"{self.base}/dql?dql={quote(query)}&items-per-page=200"
        while page:
            r = self._get(page)
            ctype = r.headers.get("Content-Type", "")
            if "json" not in ctype:  # D2 sometimes ships HTML errors with HTTP 200
                raise EridocError(f"Unexpected content type from DQL endpoint: {ctype}")
            body = r.json()
            for entry in body.get("entries", []):
                props = entry.get("content", {}).get("properties", entry.get("content", {}))
                out.append(props)
            page = next((l["href"] for l in body.get("links", [])
                         if l.get("rel") == "next"), None)
        log.debug("DQL returned %d rows", len(out))
        return out

    # -- content download ---------------------------------------------------
    def download(self, doc_id: str, dest: Path) -> Path | None:
        """Stream document content to dest. Returns None if over size cap."""
        url = f"{self.base}/objects/{doc_id}/content-media"
        with self._get(url, stream=True) as r:
            declared = int(r.headers.get("Content-Length", 0))
            if declared > self.max_doc_bytes:
                log.info("Skipping oversize document %s (%d bytes)", doc_id, declared)
                return None
            written = 0
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    written += len(chunk)
                    if written > self.max_doc_bytes:
                        fh.close()
                        dest.unlink(missing_ok=True)
                        return None
                    fh.write(chunk)
        return dest

    def self_test(self) -> None:
        """Boot-time reachability check - fail fast, never start half-alive."""
        self._get(f"{self.base}")
