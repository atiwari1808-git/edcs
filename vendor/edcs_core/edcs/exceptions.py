"""EDCS exception hierarchy. Every raised error is typed; no bare excepts."""


class EdcsError(Exception):
    """Base class for all EDCS errors."""


class ConfigError(EdcsError):
    pass


class SecurityError(EdcsError):
    """Untrusted-input violation (host not allowlisted, bad ID pattern...)."""


class MailIntakeError(EdcsError):
    pass


class EridocError(EdcsError):
    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class CloneError(EdcsError):
    pass


class ScanError(EdcsError):
    def __init__(self, msg: str, file: str = ""):
        super().__init__(msg)
        self.file = file


class ReportError(EdcsError):
    pass


class MailSendError(EdcsError):
    pass
