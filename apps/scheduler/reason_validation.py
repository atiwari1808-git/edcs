"""Shared validator for handover cancellation / reschedule reasons.

Rejects blank, too-short, or meaningless "junk" reasons (NA, None, nil, nn,
test, asdf, dots, single repeated characters, etc.) so the audit trail always
carries a real justification.

Usage:
    from apps.scheduler.reason_validation import validate_reason
    ok, cleaned_or_error = validate_reason(raw)
    if not ok:
        # cleaned_or_error is a human-readable error message
        ...
    else:
        reason = cleaned_or_error   # trimmed, length-capped text
"""
import re

# Minimum number of meaningful characters a reason must contain.
MIN_LEN = 8
MAX_LEN = 1000

# Exact-match junk tokens (compared case-insensitively, punctuation stripped).
_JUNK_TOKENS = {
    "na", "n/a", "n.a", "none", "nil", "nan", "null", "nn", "no", "no reason",
    "reason", "cancel", "cancelled", "cancellation", "test", "testing", "abc",
    "asdf", "asdfgh", "qwerty", "xxx", "xx", "aaa", "-", ".", "..", "...",
    "dummy", "sample", "tbd", "todo", "n a", "na na", "ok", "okay", "done",
}

# Patterns that indicate junk regardless of length.
_ONLY_PUNCT = re.compile(r"^[\W_]+$", re.UNICODE)
_SINGLE_CHAR_REPEAT = re.compile(r"^(.)\1*$")          # e.g. "aaaa", "----"
_NO_LETTERS = re.compile(r"^[^A-Za-z]+$")               # digits/punct only


def validate_reason(raw: str):
    """Return (True, cleaned_reason) if valid, else (False, error_message)."""
    reason = (raw or "").strip()

    if not reason:
        return False, "A cancellation reason is required."

    # Normalise for junk comparison: lowercase, collapse internal whitespace.
    norm = re.sub(r"\s+", " ", reason).strip().lower()
    # Strip surrounding punctuation for the exact-token comparison.
    norm_token = norm.strip(" .,-_/\\|!?*#")

    if norm_token in _JUNK_TOKENS or norm in _JUNK_TOKENS:
        return False, (
            "Please provide a specific, meaningful reason "
            "(values like 'NA', 'None', 'test' are not accepted)."
        )

    if _ONLY_PUNCT.match(reason):
        return False, "The reason cannot be only punctuation or symbols."

    if _SINGLE_CHAR_REPEAT.match(norm_token):
        return False, "Please provide a real reason, not repeated characters."

    if _NO_LETTERS.match(reason):
        return False, "The reason must contain words, not just numbers or symbols."

    # Count meaningful (alphanumeric) characters, ignoring spaces/punctuation.
    meaningful = re.sub(r"[\W_]+", "", reason, flags=re.UNICODE)
    if len(meaningful) < MIN_LEN:
        return False, (
            f"The reason is too short — please describe why in at least "
            f"{MIN_LEN} characters."
        )

    if len(reason) > MAX_LEN:
        reason = reason[:MAX_LEN]

    return True, reason
