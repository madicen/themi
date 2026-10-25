"""Google sign-in on the website, and linking Gmail from Telegram and the website."""

from __future__ import annotations

from html import unescape
from urllib.parse import urlsplit

import httpx

from tests.fakes.google_oauth import FakeGoogle
from tests.fixtures.web import flash, sign_in
from tests.scenarios.harness import Scenario
from themi.accounts import SYSTEM


def path_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


async def google_sign_in(
    site: httpx.AsyncClient, fake_google: FakeGoogle, address: str
) -> httpx.Response:
    start = await site.get("/auth/google")
    assert start.status_code == 303
    assert start.headers["location"].startswith(fake_google.url)
    return await site.get(path_of(fake_google.consent(start.headers["location"], address)))


async def test_sign_in_with_google(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    scenario.app.store.set_email(SYSTEM, scenario.member("Erin").id, "erin@example.com")
    signed_out = await site.get("/signed-out")
    assert 'href="/auth/google"' in signed_out.text

    done = await google_sign_in(site, fake_google, "erin@example.com")
    assert done.status_code == 303 and done.headers["location"] == "/"
    home = await site.get("/")
    assert home.status_code == 200 and "Sign out" in home.text


async def test_a_stranger_cannot_sign_in(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    refused = await google_sign_in(site, fake_google, "stranger@example.com")
    assert refused.status_code == 403
    assert "isn't one of the family's sign-in addresses" in unescape(refused.text)
    assert (await site.get("/")).status_code == 303  # still signed out


async def test_cancelling_at_google_changes_nothing(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    start = await site.get("/auth/google")
    page = await site.get(path_of(fake_google.deny(start.headers["location"])))
    assert page.status_code == 400 and "cancelled" in page.text


async def test_both_members_link_several_gmail_accounts(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    # From Telegram: the link opens in any browser, signed in or not.
    for name, address in [
        ("Erin", "erin@gmail.com"),
        ("Husband", "husband@gmail.com"),
        ("Husband", "husband.work@example.com"),
    ]:
        (reply,) = await scenario.say(name, "/link gmail")
        assert "link as many accounts as you like" in reply
        assert scenario.telegram.calls("sendMessage")[-1]["link_preview_options"] == {
            "is_disabled": True
        }
        google_url = reply.splitlines()[-1]
        landed = await site.get(path_of(fake_google.consent(google_url, address)))
        assert landed.status_code == 200 and f"Linked {address}." in landed.text

    (reply,) = await scenario.say("Husband", "/link gmail")
    assert "Already linked: husband@gmail.com, husband.work@example.com." in reply

    # From the website: My accounts → Link a Gmail account.
    csrf = await sign_in(scenario, site, "Erin")
    page = await site.get("/accounts")
    assert "erin@gmail.com" in page.text
    start = await site.post("/accounts/link", data={"csrf": csrf})
    assert start.status_code == 303 and start.headers["location"].startswith(fake_google.url)
    back = await site.get(
        path_of(fake_google.consent(start.headers["location"], "erin@rentals.example"))
    )
    assert back.status_code == 303 and back.headers["location"] == "/accounts"
    assert "Linked erin@rentals.example." in await flash(site, "/accounts")

    store = scenario.app.store
    assert [a.address for a in store.linked_accounts(scenario.member("Erin").id)] == [
        "erin@gmail.com",
        "erin@rentals.example",
    ]
    assert len(store.linked_accounts(scenario.member("Husband").id)) == 2


async def test_unlinking_from_the_website_revokes_the_token(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/link gmail")
    await site.get(path_of(fake_google.consent(reply.splitlines()[-1], "erin@gmail.com")))
    (account,) = scenario.app.store.linked_accounts(scenario.member("Erin").id)
    token = scenario.app.store.refresh_token(account.id).reveal()

    csrf = await sign_in(scenario, site, "Erin")
    assert (await site.post(f"/accounts/{account.id}/unlink", data={})).status_code == 403
    done = await site.post(f"/accounts/{account.id}/unlink", data={"csrf": csrf})
    assert done.status_code == 303
    assert "Google cancelled its access" in await flash(site, "/accounts")
    assert fake_google.state.revoked == [token]
    assert scenario.app.store.linked_accounts(scenario.member("Erin").id) == []


async def test_someone_elses_account_cannot_be_unlinked(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/link gmail")
    await site.get(path_of(fake_google.consent(reply.splitlines()[-1], "erin@gmail.com")))
    (account,) = scenario.app.store.linked_accounts(scenario.member("Erin").id)
    csrf = await sign_in(scenario, site, "Husband")
    await site.post(f"/accounts/{account.id}/unlink", data={"csrf": csrf})
    assert "isn't one of yours" in unescape(await flash(site, "/accounts"))
    assert fake_google.state.revoked == []


async def test_removing_a_member_revokes_their_tokens(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    for address in ("husband@gmail.com", "husband.work@example.com"):
        (reply,) = await scenario.say("Husband", "/link gmail")
        await site.get(path_of(fake_google.consent(reply.splitlines()[-1], address)))
    husband = scenario.member("Husband")
    csrf = await sign_in(scenario, site, "Erin")
    await site.post(
        f"/family/members/{husband.id}/remove", data={"csrf": csrf, "confirm_name": "Husband"}
    )
    assert fake_google.live_refresh_tokens("husband@gmail.com") == []
    assert fake_google.live_refresh_tokens("husband.work@example.com") == []
    assert len(fake_google.state.revoked) == 2


async def test_admins_set_sign_in_addresses(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    husband = scenario.member("Husband")
    page = await site.get("/family")
    assert f'action="/family/members/{husband.id}/email"' in page.text
    await site.post(
        f"/family/members/{husband.id}/email", data={"csrf": csrf, "email": "Him@Example.com"}
    )
    assert "can sign in with Google as him@example.com" in await flash(site, "/family")
    assert scenario.app.store.get_member(husband.id).email == "him@example.com"


async def test_linking_redirects_are_allowed_by_the_csp(
    scenario: Scenario, fake_google: FakeGoogle, site: httpx.AsyncClient
) -> None:
    response = await site.get("/signed-out")
    policy = response.headers["Content-Security-Policy"]
    assert f"form-action 'self' {fake_google.url};" in policy


async def test_without_google_set_up_the_site_says_so(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    assert scenario.app.services.google is None
    assert "Sign in with Google" not in (await site.get("/signed-out")).text
    assert (await site.get("/auth/google")).status_code == 404
    assert (
        "form-action 'self';" in (await site.get("/signed-out")).headers["Content-Security-Policy"]
    )
    csrf = await sign_in(scenario, site, "Erin")
    assert "isn't set up on this server yet" in unescape((await site.get("/accounts")).text)
    (reply,) = await scenario.say("Erin", "/link gmail")
    assert "isn't set up on this server yet" in reply
    assert csrf
