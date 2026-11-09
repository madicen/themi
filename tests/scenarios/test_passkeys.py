"""SP7b: passkeys and a recovery code, for admins who don't use Telegram. Family members
sign in as before, with the link /site sends."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from tests.fakes.passkey import FakeAuthenticator
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.accounts import SYSTEM, Role
from themi.web import HealthSources, create_app, site_base_url
from themi.web.auth import WebAuth
from themi.web.kit import SiteContext

SITE = "https://themi.example.ts.net"


@asynccontextmanager
async def site(scenario: Scenario) -> AsyncIterator[httpx.AsyncClient]:
    """The website at an https address, as passkeys need."""
    web = create_app(
        HealthSources(scenario.app.db, None, clock.now()),
        SiteContext(scenario.app, base_url=SITE, secure_cookies=True),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web), base_url=SITE, follow_redirects=False
    ) as client:
        yield client


async def add_passkey(client: httpx.AsyncClient, csrf: str, phone: FakeAuthenticator) -> None:
    options = (await client.post("/passkeys/options", headers={"X-CSRF-Token": csrf})).json()
    assert options["rp"]["id"] == "themi.example.ts.net"
    answer = await client.post(
        "/passkeys/register",
        json={"credential": phone.register(options), "name": "Erin's phone"},
        headers={"X-CSRF-Token": csrf},
    )
    assert answer.status_code == 200, answer.text


async def test_an_admin_adds_a_passkey_and_signs_in_with_it(scenario: Scenario) -> None:
    phone = FakeAuthenticator(SITE, "themi.example.ts.net")
    async with site(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        await add_passkey(client, csrf, phone)
        page = (await client.get("/passkeys")).text
        assert "Erin&#39;s phone" in page
    async with site(scenario) as browser:
        out = (await browser.get("/signed-out")).text
        assert "Sign in with a passkey" in out
        options = (await browser.post("/passkeys/sign-in/options")).json()
        answer = await browser.post(
            "/passkeys/sign-in", json={"credential": phone.sign_in(options)}
        )
        assert answer.json() == {"next": "/"}
        home = await browser.get("/")
        assert home.status_code == 200 and "Hi Erin" in home.text


async def test_a_passkey_from_another_site_or_an_old_challenge_is_refused(
    scenario: Scenario,
) -> None:
    phone = FakeAuthenticator(SITE, "themi.example.ts.net")
    async with site(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        options = (await client.post("/passkeys/options", headers={"X-CSRF-Token": csrf})).json()
        elsewhere = phone.register(options, origin="https://evil.test")
        refused = await client.post(
            "/passkeys/register", json={"credential": elsewhere}, headers={"X-CSRF-Token": csrf}
        )
        assert refused.status_code == 400
        await add_passkey(client, csrf, phone)
    async with site(scenario) as browser:
        options = (await browser.post("/passkeys/sign-in/options")).json()
        credential = phone.sign_in(options)
        assert (
            await browser.post("/passkeys/sign-in", json={"credential": credential})
        ).status_code == 200
    async with site(scenario) as replay:  # the same answer again: its challenge is used up
        await replay.post("/passkeys/sign-in/options")
        again = await replay.post("/passkeys/sign-in", json={"credential": credential})
        assert again.status_code == 400 and (await replay.get("/")).status_code == 303


async def test_the_recovery_code_works_once(scenario: Scenario) -> None:
    async with site(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        shown = (await client.post("/passkeys/recovery-code", data={"csrf": csrf})).text
        code = re.search(r'<pre class="key">([A-Z0-9-]+)</pre>', shown)
        assert code
    async with site(scenario) as browser:
        used = await browser.post("/recovery", data={"code": code.group(1).lower()})
        assert used.headers["location"] == "/passkeys"
        assert "That code is used up" in (await browser.get("/passkeys")).text
    async with site(scenario) as again:
        refused = await again.post("/recovery", data={"code": code.group(1)})
        assert refused.status_code == 400 and (await again.get("/")).status_code == 303


async def test_family_members_are_never_asked_for_a_passkey(scenario: Scenario) -> None:
    async with site(scenario) as client:
        csrf = await sign_in(scenario, client, "Husband")
        assert (await client.get("/passkeys")).status_code == 403
        refused = await client.post("/passkeys/options", headers={"X-CSRF-Token": csrf})
        assert refused.status_code == 403
        assert "/passkeys" not in (await client.get("/settings")).text
        assert "Add a passkey" not in (await client.get("/")).text


async def test_without_any_passkey_the_signed_out_page_is_as_before(scenario: Scenario) -> None:
    async with site(scenario) as browser:
        page = (await browser.get("/signed-out")).text
    assert "Sending /site to Themi in Telegram gets you a sign-in link." in page
    assert "passkey" not in page


async def test_an_admin_without_telegram_is_offered_a_passkey(scenario: Scenario) -> None:
    sam = scenario.app.store.create_member(SYSTEM, "Sam", Role.ADMIN)  # never paired
    async with site(scenario) as client:
        token = WebAuth(scenario.app.store).create_link_token(sam)
        await client.post(f"/login/{token}")
        home = (await client.get("/")).text
        assert "Add a passkey, so you can sign in again without Telegram." in home
        await sign_in(scenario, client, "Erin")  # paired with Telegram: not asked
        assert "Add a passkey" not in (await client.get("/")).text


async def test_on_one_computer_passkeys_work_at_localhost(scenario: Scenario) -> None:
    """With no public address, the site is localhost, which browsers count as secure;
    127.0.0.1 isn't, so passkeys couldn't be added there."""
    base = site_base_url("", "127.0.0.1", 8080)
    assert base == site_base_url("", "0.0.0.0", 8080) == "http://localhost:8080"
    web = create_app(
        HealthSources(scenario.app.db, None, clock.now()),
        SiteContext(scenario.app, base_url=base, secure_cookies=False),
    )
    phone = FakeAuthenticator(base, "localhost")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web), base_url=base, follow_redirects=False
    ) as client:
        csrf = await sign_in(scenario, client, "Erin")
        assert "Add a passkey" in (await client.get("/passkeys")).text
        options = (await client.post("/passkeys/options", headers={"X-CSRF-Token": csrf})).json()
        assert options["rp"]["id"] == "localhost"
        answer = await client.post(
            "/passkeys/register",
            json={"credential": phone.register(options), "name": "This Mac"},
            headers={"X-CSRF-Token": csrf},
        )
        assert answer.status_code == 200, answer.text
