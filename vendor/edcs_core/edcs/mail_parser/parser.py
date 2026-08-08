"""Inbound notification parsing: MIME walk -> Jira ID + Bitbucket URL.

The parser prefers the newest unquoted section (forwarded mails carry stale
Jira IDs in quoted history). Missing fields raise MailIntakeError."""
from __future__ import annotations

import email
import email.policy
import re

from bs4 import BeautifulSoup

from edcs.exceptions import MailIntakeError
from edcs.models import ScanJob

JIRA_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,7}\b")
URL_RE = re.compile(r"https://[^\s<>\"']+", re.I)
QUOTE_MARKERS = ("-----original message-----", "from:", "> ")


def _body_text(msg) -> str:
    body = msg.get_body(preferencelist=("plain",))
    if body is not None:
        return body.get_content()
    body = msg.get_body(preferencelist=("html",))
    if body is not None:
        return BeautifulSoup(body.get_content(), "html.parser").get_text("\n")
    return ""


def _unquoted(text: str) -> str:
    lines = []
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("-----original message-----"):
            break
        if low.startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines)


def parse_notification(raw: bytes, allowed_hosts: set[str]) -> list[ScanJob]:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    subject = msg.get("Subject", "")
    sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
    message_id = msg.get("Message-ID", "").strip()

    text = _unquoted(_body_text(msg)) + "\n" + subject
    jira_ids = list(dict.fromkeys(JIRA_RE.findall(text.upper())))
    repo_urls = [u.rstrip(".,;)>") for u in URL_RE.findall(text)
                 if any(h in u.lower() for h in allowed_hosts)]
    repo_urls = list(dict.fromkeys(repo_urls))

    if not jira_ids:
        raise MailIntakeError("No Jira ID found in notification mail")
    if not repo_urls:
        raise MailIntakeError("No allowlisted Bitbucket URL found in notification mail")

    jobs: list[ScanJob] = []
    if len(jira_ids) == len(repo_urls):
        pairs = zip(jira_ids, repo_urls)
    else:
        pairs = ((j, repo_urls[0]) for j in jira_ids)
    for jid, url in pairs:
        jobs.append(ScanJob(jira_id=jid, repo_url=url,
                            requester=sender, message_id=message_id))
    return jobs
