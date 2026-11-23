"""F56a (Michael's bug #246, "open in Gmail should open the app"): [Open in Gmail] goes
through Themi's own page, which opens the Gmail app on a phone and Gmail on the web
anywhere else."""

from __future__ import annotations

from html import unescape
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from tests.fakes.gmail_api import FakeGmail
from tests.fixtures.web import web_client
from tests.scenarios.harness import Scenario
from tests.scenarios.test_email_buttons import SCHWAB, SCHWAB_SUMMARY, alert, keyboard
from tests.scenarios.test_triage import ERIN, inbox

__all__ = ["inbox"]

SITE = "https://themi.example.ts.net"
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 Telegram-iOS"
)
ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/131 Mobile"
DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Safari/605.1.15"


@pytest.fixture
def https(scenario: Scenario, inbox: FakeGmail) -> None:
    """Themi on its https address, set after linking (whose sign-in comes back to the
    address it was linked from)."""
    scenario.app.services.site_url = SITE


def ids(scenario: Scenario, email_id: int) -> tuple[str, str]:
    row = scenario.app.db.one("SELECT gmail_id, thread_id FROM emails WHERE id = ?", (email_id,))
    assert row is not None
    return str(row["gmail_id"]), str(row["thread_id"])


async def opened(scenario: Scenario, inbox: FakeGmail) -> tuple[int, str]:
    email_id = await alert(scenario, inbox, SCHWAB, SCHWAB_SUMMARY)
    return email_id, keyboard(scenario)[0]["url"]


async def visit(scenario: Scenario, url: str, agent: str) -> tuple[int, str, str]:
    """The page at `url`, signed out, as `agent`: status, text, and where it redirects."""
    parts = urlsplit(url)
    async with web_client(scenario) as client:
        page = await client.get(
            f"{parts.path}?{parts.query}", headers={"user-agent": agent}, follow_redirects=False
        )
    return page.status_code, unescape(page.text), page.headers.get("location", "")


@pytest.mark.usefixtures("https")
async def test_the_button_is_a_signed_link_to_themis_page(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    email_id, url = await opened(scenario, inbox)
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{SITE}/open/email/{email_id}"
    assert parse_qs(parts.query)["s"][0]
    assert "callback_data" not in keyboard(scenario)[0]


@pytest.mark.usefixtures("https")
async def test_an_iphone_gets_the_gmail_apps_link_and_both_fallbacks(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    """F58a (bug #247): `googlegmail:///cv=` made the app say "Unable to understand the
    link", so until a form is chosen the app link is the inbox."""
    email_id, url = await opened(scenario, inbox)
    gmail_id, _ = ids(scenario, email_id)
    status, text, _ = await visit(scenario, url, IPHONE)
    assert status == 200
    assert 'data-app="googlegmail://"' in text and "cv=" not in text
    assert 'href="googlegmail://"' in text and "Open the Gmail app" in text
    assert f'href="https://mail.google.com/mail/u/{ERIN}/#all/{gmail_id}"' in text
    assert "Open in Gmail on the web" in text
    assert "Schwab" in text and "Your November snapshot" in text and ERIN in text
    assert "/static/google/open-email.js" in text


@pytest.mark.usefixtures("https")
async def test_android_gets_an_intent_with_the_web_link_as_fallback(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    email_id, url = await opened(scenario, inbox)
    gmail_id, _ = ids(scenario, email_id)
    status, text, _ = await visit(scenario, url, ANDROID)
    web = f"https://mail.google.com/mail/u/{ERIN}/#all/{gmail_id}"
    assert status == 200
    assert "package=com.google.android.gm" in text
    assert f"S.browser_fallback_url={quote(web, safe='')}" in text


@pytest.mark.usefixtures("https")
async def test_a_computer_goes_straight_to_gmail_on_the_web(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    email_id, url = await opened(scenario, inbox)
    gmail_id, _ = ids(scenario, email_id)
    status, _, location = await visit(scenario, url, DESKTOP)
    assert (status, location) == (303, f"https://mail.google.com/mail/u/{ERIN}/#all/{gmail_id}")


@pytest.mark.usefixtures("https")
async def test_a_wrong_signature_or_a_gone_email_is_404(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    email_id, url = await opened(scenario, inbox)
    status, text, _ = await visit(scenario, f"{SITE}/open/email/{email_id}?s=nope", IPHONE)
    assert status == 404 and "That email isn't here any more." in text
    other = url.replace(f"/open/email/{email_id}?", f"/open/email/{email_id + 1}?")
    assert (await visit(scenario, other, IPHONE))[0] == 404  # can't be walked to another
    scenario.app.db.execute("DELETE FROM emails WHERE id = ?", (email_id,))
    status, text, _ = await visit(scenario, url, IPHONE)
    assert status == 404 and "That email isn't here any more." in text


async def test_without_an_https_site_the_button_is_gmails_web_link(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    email_id, url = await opened(scenario, inbox)
    gmail_id, _ = ids(scenario, email_id)
    assert url == f"https://mail.google.com/mail/u/{ERIN}/#all/{gmail_id}"


# ----- F58a (bug #247): the try-out page, and the chosen form ------------------------------


def try_url(url: str) -> str:
    return url.replace("?s=", "/try?s=")


@pytest.mark.usefixtures("https")
async def test_the_try_out_page_lists_every_candidate_link(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    email_id, url = await opened(scenario, inbox)
    gmail_id, _ = ids(scenario, email_id)
    thread_id = "1a206bcb61e9dd07"  # as Gmail's are (the fake's aren't hex)
    scenario.app.db.execute("UPDATE emails SET thread_id = ? WHERE id = ?", (thread_id, email_id))
    status, text, _ = await visit(scenario, try_url(url), IPHONE)
    assert status == 200
    msgid = quote(f"{gmail_id}@mail.example", safe="")
    links = [
        f"googlegmail:///cv={thread_id}/accountId=1&create-new-tab",
        f"googlegmail:///cv={thread_id}/accountId=2&create-new-tab",
        f"googlegmail:///cv={int(thread_id, 16)}/accountId=1&create-new-tab",
        f"googlegmail://search?q=rfc822msgid:{msgid}",
        f"googlegmail:///search?q=rfc822msgid:{msgid}",
        "googlegmail://",
    ]
    for number, link in enumerate(links, 1):
        assert f'href="{link}"' in text, link
        assert f"{number}. " in text
    assert "Your November snapshot" in text and ERIN in text


@pytest.mark.usefixtures("https")
async def test_the_try_out_page_needs_the_signature_and_skips_search_without_a_message_id(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    email_id, url = await opened(scenario, inbox)
    bad = f"{SITE}/open/email/{email_id}/try?s=nope"
    assert (await visit(scenario, bad, IPHONE))[0] == 404
    scenario.app.db.execute("UPDATE emails SET message_id_header = NULL WHERE id = ?", (email_id,))
    status, text, _ = await visit(scenario, try_url(url), IPHONE)
    assert status == 200
    assert "rfc822msgid" not in text and "5. " not in text and 'href="googlegmail://"' in text


@pytest.mark.usefixtures("https")
async def test_the_chosen_form_and_the_accounts_place_in_the_app(
    scenario: Scenario, inbox: FakeGmail
) -> None:
    from themi_google.web.open_email import THREAD, EmailLinkSettings

    email_id, url = await opened(scenario, inbox)
    _, thread_id = ids(scenario, email_id)
    store = scenario.app.services.store
    admin = next(m for m in store.list_members() if m.is_admin)
    store.save_household(
        admin,
        EmailLinkSettings,
        gmail_iphone_link=THREAD,
        gmail_app_order=f"someone.else@gmail.com, {ERIN}",
    )
    status, text, _ = await visit(scenario, url, IPHONE)
    assert status == 200
    assert f'data-app="googlegmail:///cv={thread_id}/accountId=2&create-new-tab"' in text
    assert 'href="googlegmail://"' in text  # the inbox is still the fallback button
