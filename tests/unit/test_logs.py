import logging
import sys

import pytest

from themi.logs import REDACTED, RedactingFilter, RedactingFormatter, redact

# Fake credentials in each provider's shape. None of these are real.
SAMPLES = {
    "telegram": "7123456789:AAH4fakeTelegramTokenValue_abcdefghijk",
    "anthropic": "sk-ant-api03-FAKEfakeFAKEfakeFAKEfakeFAKEfake-123",
    "openai_style": "sk-proj-FAKEfakeFAKEfakeFAKEfake12",
    "gemini": "AIzaSyFAKE-fake_FAKEfakeFAKEfakeFAKE123",
    "google_access": "ya29.a0FAKEfakeFAKEfakeFAKEfakeFAKEfake",
    "google_refresh": "1//0gFAKEfakeFAKEfakeFAKEfake",
}


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_known_token_shapes_are_redacted(kind: str) -> None:
    token = SAMPLES[kind]
    line = redact(f"calling provider with {token} now")
    assert token not in line
    assert REDACTED in line
    assert line.startswith("calling provider with") and line.endswith("now")


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("Authorization: Bearer abc.def.ghi", "Authorization: "),
        ("api_key=supersecretvalue next", "api_key="),
        ('{"token": "abc123xyz", "ok": 1}', '"token": "'),
        ("password: hunter2", "password: "),
    ],
)
def test_sensitive_key_value_pairs_are_redacted(text: str, kept: str) -> None:
    line = redact(text)
    assert kept in line
    assert REDACTED in line
    for secret in ("abc.def.ghi", "supersecretvalue", "abc123xyz", "hunter2"):
        assert secret not in line


def test_ordinary_text_is_untouched() -> None:
    line = "Washer finished at 14:05; Erin has 2 pending approvals (task 12345)."
    assert redact(line) == line


def test_formatter_redacts_tracebacks() -> None:
    formatter = RedactingFormatter("%(message)s")
    try:
        raise RuntimeError(f"request failed for key {SAMPLES['gemini']}")
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())
    output = formatter.format(record)
    assert SAMPLES["gemini"] not in output
    assert "RuntimeError" in output


def test_filter_redacts_message_arguments() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "token is %s", (SAMPLES["telegram"],), None
    )
    assert RedactingFilter().filter(record)
    assert SAMPLES["telegram"] not in record.getMessage()


def test_configure_logging_quiets_libraries_that_log_contents() -> None:
    from themi.logs import CHATTY_LIBRARIES, configure_logging

    configure_logging("DEBUG")
    try:
        assert logging.getLogger().level == logging.DEBUG
        for name in CHATTY_LIBRARIES:
            assert logging.getLogger(name).level == logging.WARNING
    finally:
        logging.getLogger().handlers.clear()
        logging.getLogger().setLevel(logging.WARNING)
