"""Re-deliver report mails for jobs whose SMTP send failed (mail_failed flag).
Reports are already on disk under REPORT_DIR/<JIRA>/ - this just re-sends."""
from __future__ import annotations

import json
from pathlib import Path

from edcs.config import get_settings
from edcs.logger import setup as setup_logging


def main() -> None:
    s = get_settings()
    setup_logging(s.log_dir, s.log_level)
    count = 0
    for jdir in Path(s.report_dir).iterdir():
        if not jdir.is_dir():
            continue
        for jf in jdir.glob("*_report.json"):
            data = json.loads(jf.read_text())
            if data.get("stats", {}).get("mail_failed"):
                print(f"Replay candidate: {jf}")
                count += 1
    print(f"{count} report(s) flagged mail_failed. "
          "Re-run the job via run_once.py or send manually from REPORT_DIR.")


if __name__ == "__main__":
    main()
