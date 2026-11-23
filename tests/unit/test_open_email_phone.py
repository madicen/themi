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


# ----- F58a: the Gmail app's link in the chosen form ------------------------------------


def test_app_link_falls_back_to_the_inbox_when_the_form_cant_be_built() -> None:
    from themi_google.web.open_email import (
        INBOX,
        SEARCH,
        THREAD,
        THREAD_DECIMAL,
        app_link,
    )

    assert app_link(INBOX, "1a2b", "<x@y>", 1) == "googlegmail://"
    assert app_link(THREAD, "1a2b", None, 2) == "googlegmail:///cv=1a2b/accountId=2&create-new-tab"
    assert app_link(THREAD_DECIMAL, "ff", None, 1) == (
        "googlegmail:///cv=255/accountId=1&create-new-tab"
    )
    assert app_link(THREAD_DECIMAL, "not-hex", None, 1) == "googlegmail://"
    assert app_link(SEARCH, "1a2b", None, 1) == "googlegmail://"
    assert app_link(SEARCH, "1a2b", "<a+b@c.d>", 1) == (
        "googlegmail://search?q=rfc822msgid:a%2Bb%40c.d"
    )
