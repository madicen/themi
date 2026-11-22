"""F56a: which phone the open-email page is talking to."""

from __future__ import annotations

import pytest

from themi_google.web.open_email import phone


@pytest.mark.parametrize(
    ("agent", "kind"),
    [
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Mobile/15E148", "ios"),
        ("Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) Mobile/15E148", "ios"),
        ("Mozilla/5.0 (Linux; Android 15; Pixel 9) Chrome/131 Mobile", "android"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Safari/605.1.15", ""),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131", ""),
        ("", ""),
    ],
)
def test_phone(agent: str, kind: str) -> None:
    assert phone(agent) == kind
