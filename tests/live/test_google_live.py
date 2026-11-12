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
from themi.storage.secrets import Secret
from themi_google.connectors.gcal import CalendarClient
from themi_google.connectors.gmail import GmailClient
from themi_google.connectors.google import GoogleConfig, GoogleOAuth

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


@pytest.mark.skipif(
    not os.environ.get("THEMI_LIVE_COOKBOOK_DOC"),
    reason="set THEMI_LIVE_COOKBOOK_DOC (the cookbook's doc id, picked by the test account)",
)
async def test_the_real_cookbook_reads(token: Secret) -> None:
    """RC1a: the family's real cookbook parses with the counts read on 2026-11-06 (132
    entries). The test account must have picked the doc in Google's file picker."""
    from themi_google.connectors.gdocs import DocsClient
    from themi_home import cookbook as book

    async def source() -> Secret:
        return token

    docs = DocsClient(
        "https://docs.googleapis.com", "https://www.googleapis.com", source, lambda: None
    )
    doc_id = os.environ["THEMI_LIVE_COOKBOOK_DOC"]
    record = await docs.file(doc_id)
    assert record["mimeType"] == "application/vnd.google-apps.document"
    parsed = book.parse(await docs.get(doc_id))
    assert len(parsed.recipes) >= 132
    assert {"Breakfast", "Entrees", "Desserts", "References"} <= {s for s, _ in parsed.sections}
    biryani = next(r for r in parsed.recipes if r.name == "Biryani")
    assert biryani.steps and "two Ingredients headings" in biryani.needs_look


@pytest.mark.skipif(
    not os.environ.get("THEMI_LIVE_SHEETS"),
    reason="set THEMI_LIVE_SHEETS=1 (the refresh token needs drive.file and the Sheets API on)",
)
async def test_a_spreadsheet_round_trip(token: Secret) -> None:
    """EX4a: make a spreadsheet, a tab, rows by their hidden id, a colour and a note. It's
    left in the test account's Drive, named so it's easy to find and delete."""
    from themi_google.connectors.gsheets import Cell, SheetsClient

    async def source() -> Secret:
        return token

    sheets = SheetsClient("https://sheets.googleapis.com", source, lambda: None)
    sid, (tab, *_) = await sheets.create("Themi live test (safe to delete)", ["Business"])
    await sheets.add_tab(sid, "Mileage", 1)
    assert [t.title for t in await sheets.tabs(sid)] == ["Business", "Mileage"]
    await sheets.upsert(sid, tab, ["Amount"], {"1": [Cell(12.5, "a note", (0.85, 0.94, 0.83))]})
    await sheets.upsert(sid, tab, ["Amount"], {"1": [Cell(13)]})
    assert await sheets.ids(sid, "Business") == ["", "1"]
