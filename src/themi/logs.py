"""Logging with secret redaction.

Anything that looks like a credential is masked in the final log line,
including text inside exception tracebacks. This is a safety net: code
should still pass `Secret` objects around rather than raw strings.
"""

from __future__ import annotations

import logging
import re
import sys

REDACTED = "[redacted]"

PATTERNS = [
    # Telegram bot token: <bot id>:<35-char secret>
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}"),
    # Anthropic API keys
    re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    # OpenAI-style keys (OpenAI, OpenRouter, some local servers)
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    # Google API keys (Gemini)
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    # Google OAuth access and refresh tokens
    re.compile(r"\bya29\.[0-9A-Za-z_.-]{20,}"),
    re.compile(r"\b1//[0-9A-Za-z_-]{20,}"),
    # Fernet tokens (our own ciphertext; harmless but noisy)
    re.compile(r"\bgAAAAA[0-9A-Za-z_=-]{20,}"),
    # Authorization headers
    re.compile(r"(?i)(bearer\s+)[^\s'\"]+"),
    # key=value / key: value for sensitive-sounding names
    re.compile(
        r"(?i)((?:api[_-]?key|token|secret|password|passwd|authorization)['\"]?\s*[:=]\s*['\"]?)"
        r"[^\s'\",}]+"
    ),
]


def redact(text: str) -> str:
    for pattern in PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactingFilter(logging.Filter):
    """For handlers that don't use RedactingFormatter: redacts the message itself."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


# Libraries that log message contents or credentials-in-URLs below WARNING.
CHATTY_LIBRARIES = ("telegram", "httpx", "httpx2", "httpcore", "hpack")


def quiet_chatty_libraries() -> None:
    for name in CHATTY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    quiet_chatty_libraries()
