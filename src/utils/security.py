"""Centralized input-sanitization helpers.

Two layers:
- sanitize_user_text: clip length, strip control characters, reject empty.
  Applied to every chat input before it reaches the model.
- sanitize_for_log: redact what looks like API keys before we log a string,
  in case a stack-trace ever lands in CloudWatch / GitHub Actions output.
"""
from __future__ import annotations

import re
from typing import Final

MAX_USER_INPUT_CHARS: Final[int] = 2000

# Control characters except common whitespace (tab, newline, carriage return).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Aggressive but cheap: anything that looks like a long alphanumeric token
# next to common key keywords gets redacted in logs.
_KEY_LIKE_RE = re.compile(
    r"(api[_-]?key|secret|token|bearer)[\s:=\"']*[A-Za-z0-9_\-]{20,}",
    flags=re.IGNORECASE,
)


def sanitize_user_text(text: str | None, *, max_chars: int = MAX_USER_INPUT_CHARS) -> str:
    """Return a safe version of user-supplied text. Empty string if input is
    None, empty, or all whitespace after sanitization."""
    if text is None:
        return ""
    cleaned = _CONTROL_CHARS_RE.sub("", text).strip()
    return cleaned[:max_chars]


def sanitize_for_log(message: str) -> str:
    """Redact obvious secret-looking tokens before logging. Best-effort only."""
    return _KEY_LIKE_RE.sub(r"\1=***REDACTED***", message)
