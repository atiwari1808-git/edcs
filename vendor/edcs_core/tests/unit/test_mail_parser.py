import pytest

from edcs.exceptions import MailIntakeError
from edcs.mail_parser.parser import parse_notification

HOSTS = {"bitbucket.xxx.com"}


def _mail(body, subject="Notification"):
    return (f"From: jira@internal.ericsson.com\r\nTo: edcs@x\r\n"
            f"Subject: {subject}\r\nMessage-ID: <m1@x>\r\n"
            f"Content-Type: text/plain\r\n\r\n{body}").encode()


def test_parses_jira_and_repo():
    raw = _mail("Jira ID: ABCD-1234\n"
                "Repository: https://bitbucket.xxx.com/projects/OSS/repos/project\n")
    jobs = parse_notification(raw, HOSTS)
    assert jobs[0].jira_id == "ABCD-1234"
    assert "bitbucket.xxx.com" in jobs[0].repo_url


def test_missing_jira_raises():
    raw = _mail("Repository: https://bitbucket.xxx.com/projects/OSS/repos/p\n")
    with pytest.raises(MailIntakeError):
        parse_notification(raw, HOSTS)


def test_non_allowlisted_url_rejected():
    raw = _mail("Jira ID: ABCD-1234\nRepo: https://evil.example.com/x\n")
    with pytest.raises(MailIntakeError):
        parse_notification(raw, HOSTS)


def test_quoted_history_ignored():
    raw = _mail("Jira ID: ABCD-1234\n"
                "https://bitbucket.xxx.com/projects/OSS/repos/new\n"
                "-----Original Message-----\nJira ID: OLDX-9\n")
    jobs = parse_notification(raw, HOSTS)
    assert [j.jira_id for j in jobs] == ["ABCD-1234"]
