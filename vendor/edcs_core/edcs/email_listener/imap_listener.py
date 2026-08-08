"""IMAP intake daemon.

- IMAP4_SSL + IDLE (imapclient) with poll fallback
- sender allowlist: the mail body drives DQL + git clone, so intake is an
  attack surface - unknown senders go to INBOX/Ignored
- Message-ID idempotency via the queue's UNIQUE constraint
- Processed -> INBOX/Processed, failures -> INBOX/Failed (mailbox = DLQ)
"""
from __future__ import annotations

import email.utils
import logging
import time

from imapclient import IMAPClient

from edcs.config import get_settings
from edcs.exceptions import MailIntakeError
from edcs.logger import setup as setup_logging
from edcs.mail_parser.parser import parse_notification
from edcs.queue import JobQueue

log = logging.getLogger(__name__)

FOLDER_PROCESSED = "INBOX/Processed"
FOLDER_FAILED = "INBOX/Failed"
FOLDER_IGNORED = "INBOX/Ignored"


def _ensure_folders(client: IMAPClient) -> None:
    for f in (FOLDER_PROCESSED, FOLDER_FAILED, FOLDER_IGNORED):
        if not client.folder_exists(f):
            client.create_folder(f)


def _handle(client: IMAPClient, uid: int, raw: bytes, queue: JobQueue,
            allowed_senders: set[str], allowed_hosts: set[str]) -> None:
    msg_from = ""
    try:
        import email as email_mod
        parsed = email_mod.message_from_bytes(raw)
        msg_from = email.utils.parseaddr(parsed.get("From", ""))[1].lower()
        if allowed_senders and msg_from not in allowed_senders:
            log.warning("Ignoring mail from non-allowlisted sender %s", msg_from)
            client.move([uid], FOLDER_IGNORED)
            return
        jobs = parse_notification(raw, allowed_hosts)
        enqueued = sum(1 for j in jobs if queue.enqueue(j))
        log.info("Enqueued %d/%d job(s) from %s", enqueued, len(jobs), msg_from)
        client.move([uid], FOLDER_PROCESSED)
    except MailIntakeError as e:
        log.error("Malformed notification from %s: %s", msg_from, e)
        client.move([uid], FOLDER_FAILED)
    except Exception:
        log.exception("Intake failure for uid %s", uid)
        client.move([uid], FOLDER_FAILED)


def run() -> None:
    s = get_settings()
    setup_logging(s.log_dir, s.log_level)
    queue = JobQueue(s.tmp_dir / "queue.db")
    backoff = 5
    while True:
        try:
            with IMAPClient(s.imap_host, port=s.imap_port, ssl=True) as client:
                client.login(s.imap_username, s.imap_password.get_secret_value())
                _ensure_folders(client)
                client.select_folder(s.imap_folder)
                log.info("IMAP connected; watching %s", s.imap_folder)
                backoff = 5
                while True:
                    for uid in client.search("UNSEEN"):
                        raw = client.fetch([uid], ["RFC822"])[uid][b"RFC822"]
                        _handle(client, uid, raw, queue,
                                s.allowed_senders, s.allowed_hosts)
                    try:  # IDLE; re-issue before the 30-minute RFC limit
                        client.idle()
                        client.idle_check(timeout=min(s.imap_poll_seconds * 5, 1500))
                        client.idle_done()
                    except Exception:  # server without IDLE -> plain polling
                        time.sleep(s.imap_poll_seconds)
        except Exception as e:
            log.error("IMAP connection lost (%s); reconnect in %ss", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    run()
