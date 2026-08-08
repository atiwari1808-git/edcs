"""Central secret masking. Applied at Finding construction time so unmasked
values never leave the scanner - reports full of live passwords are a leak."""
from __future__ import annotations

import re


def mask_secret(text: str, keep: int = 2, max_len: int = 60) -> str:
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len]
    if len(text) <= keep * 2 + 2:
        return "*" * len(text)
    return f"{text[:keep]}{'*' * (len(text) - keep * 2)}{text[-keep:]}"


def mask_url(url: str) -> str:
    """https://user:token@host/... -> https://user:***@host/..."""
    return re.sub(r"(://[^/:@\s]+:)[^@\s]+(@)", r"\1***\2", url)


def mask_line(line: str, secret: str) -> str:
    """Show the line with the secret portion masked - context stays useful."""
    if secret and secret in line:
        line = line.replace(secret, mask_secret(secret))
    return line.strip()[:200]
