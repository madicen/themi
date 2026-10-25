"""Logging with secret redaction.

Anything that looks like a credential is masked in the final log line,
including text inside exception tracebacks. This is a safety net: code
should still pass `Secret` objects around rather than raw strings.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from collections import deque

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


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class RecentLogs(logging.Handler):
    """The latest log lines in memory, formatted and redacted as on the console.

    Feedback reports (/bug) attach the tail; the dev simulator's session report
    reads everything `since` a mark.
    """

    def __init__(self, capacity: int = 5000) -> None:
        super().__init__()
        self.setFormatter(RedactingFormatter(LOG_FORMAT))
        self._lines: deque[tuple[int, str]] = deque(maxlen=capacity)
        self._lines_lock = threading.Lock()
        self.count = 0  # lines seen so far, including any that fell off the end

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with self._lines_lock:
            self.count += 1
            self._lines.append((self.count, line))

    def since(self, count: int) -> list[str]:
        with self._lines_lock:
            return [line for n, line in self._lines if n > count]

    def tail(self, lines: int) -> list[str]:
        with self._lines_lock:
            return [line for _, line in list(self._lines)[-lines:]] if lines > 0 else []


# What `themi run` logged lately (configure_logging attaches it).
recent_logs = RecentLogs(capacity=500)

# Libraries that log message contents or credentials-in-URLs below WARNING.
CHATTY_LIBRARIES = ("telegram", "httpx", "httpx2", "httpcore", "hpack")


def quiet_chatty_libraries() -> None:
    for name in CHATTY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler, recent_logs]
    root.setLevel(level)
    quiet_chatty_libraries()
