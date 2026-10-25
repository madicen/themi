"""Smoke tests against real Google APIs with a test account. Opt-in: `make test-live`.

Needs a Gmail account used only for testing, linked once by hand:
- THEMI_LIVE_GOOGLE_CLIENT_ID, THEMI_LIVE_GOOGLE_CLIENT_SECRET   the OAuth client
- THEMI_LIVE_GOOGLE_REFRESH_TOKEN    a refresh token for the test account, with the
                                     gmail.modify and calendar scopes (README: Google setup)
"""

from __future__ import annotations

import os

import pytest

from tests.fixtures.family import SeededFamily
from themi.connectors.gcal import CalendarClient
from themi.connectors.gmail import GmailClient
from themi.connectors.google import GoogleConfig, GoogleOAuth
from themi.storage.secrets import Secret

NAMES = (
    "THEMI_LIVE_GOOGLE_CLIENT_ID",
    "THEMI_LIVE_GOOGLE_CLIENT_SECRET",
    "THEMI_LIVE_GOOGLE_REFRESH_TOKEN",
)

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(n) for n in NAMES), reason=f"set {', '.join(NAMES)}"
)


@pytest.fixture
async def token(family: SeededFamily) -> Secret:
    config = GoogleConfig(
        os.environ["THEMI_LIVE_GOOGLE_CLIENT_ID"],
        Secret(os.environ["THEMI_LIVE_GOOGLE_CLIENT_SECRET"]),
    )
    oauth = GoogleOAuth(family.db, family.store.cipher, config)
    access = await oauth.refresh(Secret(os.environ["THEMI_LIVE_GOOGLE_REFRESH_TOKEN"]))
    return access.token


async def test_gmail_profile_list_and_labels(token: Secret) -> None:
    async def source() -> Secret:
        return token

    gmail = GmailClient("https://gmail.googleapis.com", source, lambda: None)
    profile = await gmail.profile()
    assert "@" in profile["emailAddress"] and profile["historyId"]
    ids, _ = await gmail.list_messages("newer_than:30d")
    for message_id in ids[:3]:
        message = await gmail.get_message(message_id)
        assert message is None or message["id"] == message_id
    assert any(label["id"] == "INBOX" for label in await gmail.labels())


async def test_calendar_list(token: Secret) -> None:
    async def source() -> Secret:
        return token

    calendar = CalendarClient("https://www.googleapis.com", source, lambda: None)
    calendars = await calendar.calendars()
    assert calendars, "a Google account always has at least its primary calendar"
    assert all("id" in c and "accessRole" in c for c in calendars)
