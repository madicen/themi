"""New Gmail reaches the app as EmailReceived; a dead link is mentioned once."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.scenarios.harness import Scenario
from themi.connectors.gmail import EmailReceived
from themi.connectors.gmail.sync import RELINK_ALERT


async def link(
    scenario: Scenario, site: httpx.AsyncClient, fake_google: FakeGoogle, name: str, address: str
) -> None:
    (reply,) = await scenario.say(name, "/link gmail")
    callback = urlsplit(fake_google.consent(reply.splitlines()[-1], address))
    assert (await site.get(f"{callback.path}?{callback.query}")).status_code == 200


async def test_new_mail_reaches_email_received(
    scenario: Scenario, fake_google: FakeGoogle, fake_gmail: FakeGmail, site: httpx.AsyncClient
) -> None:
    gmail = scenario.app.services.gmail
    assert gmail is not None
    received: list[EmailReceived] = []

    async def listen(event: EmailReceived) -> None:
        received.append(event)

    gmail.listeners.append(listen)
    await link(scenario, site, fake_google, "Erin", "erin@gmail.com")
    await link(scenario, site, fake_google, "Husband", "him@gmail.com")
    await scenario.run_periodic("gmail.poll")  # first sync: empty inboxes

    fake_gmail.deliver(
        "him@gmail.com",
        sender="Property Manager <pm@rentals.example>",
        subject="Unit 2: water leak",
        html="<p>Tenant reports a <b>leak</b> under the sink.</p>",
    )
    await scenario.advance(minutes=3)
    await scenario.run_periodic("gmail.poll")

    (event,) = received
    assert event.member_id == scenario.member("Husband").id and not event.initial
    assert event.message.subject == "Unit 2: water leak"
    assert event.message.text == "Tenant reports a leak under the sink."
    assert event.message.from_address == "pm@rentals.example"


async def test_a_revoked_link_is_mentioned_once_in_telegram(
    scenario: Scenario, fake_google: FakeGoogle, fake_gmail: FakeGmail, site: httpx.AsyncClient
) -> None:
    await link(scenario, site, fake_google, "Erin", "erin@gmail.com")
    await scenario.run_periodic("gmail.poll")
    fake_google.revoke_everything_for("erin@gmail.com")
    fake_google.state.access_tokens.clear()
    texts: list[str] = []
    for _ in range(4):
        texts += await scenario.advance(hours=1)
        await scenario.run_periodic("gmail.poll")
        texts += await scenario.advance(minutes=1)
    alert = RELINK_ALERT.format(address="erin@gmail.com")
    assert [t for t in scenario.inbox("Erin") if "erin@gmail.com any more" in t] == [alert]
