"""Outbound SMTP: STARTTLS, multipart HTML+plain, attachments with size guard,
retries; final failure leaves the report on disk for replay_failed.py."""
from __future__ import annotations

import logging
import mimetypes
import smtplib
import zipfile
from email.message import EmailMessage
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_fixed

from edcs.config import Settings
from edcs.exceptions import MailSendError
from edcs.models import ScanResult

log = logging.getLogger(__name__)


class Mailer:
    def __init__(self, s: Settings):
        self.s = s

    def _attach(self, msg: EmailMessage, path: Path) -> None:
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype,
                           subtype=subtype, filename=path.name)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(120), reraise=True)
    def _send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=60) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_username:
                smtp.login(self.s.smtp_username,
                           self.s.smtp_password.get_secret_value())
            smtp.send_message(msg)

    def send_report(self, r: ScanResult, html_body: str,
                    attachments: list[Path]) -> None:
        code_count = len(r.code_findings)
        subject = (f"[EDCS][{r.overall_status.value}] {r.job.jira_id} - "
                   f"Compliance {r.compliance_score}% - {code_count} code findings")
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.s.mail_from
        to = list(self.s.recipients)
        if self.s.mail_cc_requester and r.job.requester:
            to.append(r.job.requester)
        if not to:
            raise MailSendError("No recipients configured (MAIL_RECIPIENTS)")
        msg["To"] = ", ".join(dict.fromkeys(to))
        msg.set_content("Your mail client cannot render HTML. "
                        "See the attached report files.")
        msg.add_alternative(html_body, subtype="html")

        total = sum(p.stat().st_size for p in attachments)
        cap = self.s.mail_max_attach_mb * 1024 * 1024
        if total > cap:  # zip; if still oversized, ship the summary + path only
            zpath = attachments[0].parent / f"{r.job.jira_id}_{r.job.job_id}_reports.zip"
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in attachments:
                    zf.write(p, p.name)
            attachments = [zpath] if zpath.stat().st_size <= cap else []
            if not attachments:
                msg.add_alternative(html_body + f"<p>Reports too large to attach; "
                                    f"stored at {zpath.parent}</p>", subtype="html")
        for p in attachments:
            self._attach(msg, p)

        try:
            self._send(msg)
            log.info("Report mail sent: %s", subject)
        except Exception as e:
            raise MailSendError(f"SMTP send failed after retries: {e}") from e
