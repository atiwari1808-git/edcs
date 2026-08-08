"""Validated configuration. Import-time fail-fast via pydantic-settings.

Every module imports `get_settings()`; nothing reads os.environ directly.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from edcs.models import Severity


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ERIDOC
    eridoc_rest_url: str
    eridoc_repository: str
    eridoc_username: str
    eridoc_password: SecretStr
    eridoc_verify_tls: bool = True
    eridoc_ca_bundle: str = ""
    eridoc_timeout_s: int = 30
    eridoc_max_doc_mb: int = 200
    eridoc_root_path: str = ""

    # Bitbucket
    bitbucket_username: str
    bitbucket_token: SecretStr
    bitbucket_allowed_hosts: str
    clone_dir: Path = Path("/var/tmp/edcs/clones")
    clone_depth: int = 1
    clone_timeout_s: int = 600
    max_repo_mb: int = 2048

    # IMAP
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: SecretStr = SecretStr("")
    imap_folder: str = "INBOX"
    imap_allowed_senders: str = ""
    imap_poll_seconds: int = 60

    # SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = True
    mail_from: str = "edcs-noreply@example.com"
    mail_recipients: str = ""
    mail_cc_requester: bool = True
    mail_max_attach_mb: int = 15

    # Policy
    mandatory_docs_file: Path = Path("config/mandatory_documents.yaml")
    secret_rules_file: Path = Path("config/secret_rules.yaml")
    allowed_extensions: str = ".py,.sh,.yml,.yaml,.json,.ini,.cfg,.conf,.xml,.properties,.java,.sql,.tf,.env,.txt,.md,.toml"
    excluded_dirs: str = ".git,node_modules,venv,.venv,dist,build,target,__pycache__"
    max_file_mb: int = 10
    severity_fail_threshold: str = "HIGH"
    compliance_pass_score: int = 90

    # Runtime
    tmp_dir: Path = Path("/var/tmp/edcs")
    report_dir: Path = Path("/var/lib/edcs/reports")
    history_db_url: str = "sqlite:////var/lib/edcs/history.db"
    workers: int = 4
    log_level: str = "INFO"
    log_dir: Path = Path("/var/log/edcs")

    # -- derived helpers -------------------------------------------------
    @property
    def allowed_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.bitbucket_allowed_hosts.split(",") if h.strip()}

    @property
    def allowed_ext_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()}

    @property
    def excluded_dir_set(self) -> set[str]:
        return {d.strip() for d in self.excluded_dirs.split(",") if d.strip()}

    @property
    def allowed_senders(self) -> set[str]:
        return {s.strip().lower() for s in self.imap_allowed_senders.split(",") if s.strip()}

    @property
    def recipients(self) -> list[str]:
        return [r.strip() for r in self.mail_recipients.split(",") if r.strip()]

    @property
    def fail_threshold(self) -> Severity:
        return Severity(self.severity_fail_threshold.upper())

    @field_validator("bitbucket_allowed_hosts")
    @classmethod
    def _non_empty_hosts(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("BITBUCKET_ALLOWED_HOSTS must not be empty")
        return v

    @field_validator("severity_fail_threshold")
    @classmethod
    def _valid_severity(cls, v: str) -> str:
        Severity(v.upper())
        return v.upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    for p in (s.tmp_dir, s.clone_dir, s.report_dir, s.log_dir):
        Path(p).mkdir(parents=True, exist_ok=True)
    return s
