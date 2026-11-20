"""WL8: parcels from shipping emails, in Themi's note on the wall. Erin's inbox is linked
and watched; the day is Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import web_client
from tests.integration.test_wall_screen import frame, task, with_wall, words
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, arrive, link, verdict
from themi.core import keys
from themi_home.wall_view import WallSettings

NO_DELIVERY = {"shop": "", "date": "", "status": ""}


@pytest.fixture
async def mail(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    fake_google: FakeGoogle,
    fake_gmail: FakeGmail,
) -> AsyncIterator[Scenario]:
    s = with_wall(family, fake_telegram, google=fake_google, gmail=fake_gmail)
    await s.start()
    try:
        async with web_client(s) as site:
            await link(s, site, fake_google, "Erin", ERIN)
        await s.tap("Erin", "Watch it")
        await s.run_periodic("gmail.poll")
        yield s
    finally:
        await s.stop()


async def shipping(
    s: Scenario, shop: str, status: str, day: str = "2026-10-21", category: str = "routine"
) -> None:
    """A shipping email from a shop about a parcel with a present in it, sorted."""
    inbox: FakeGmail = s.gmail  # type: ignore[assignment]
    [email] = await arrive(
        s,
        inbox,
        {
            "sender": f"{shop} <ship@{shop.lower()}.example>",
            "subject": "Your order is on its way",
            "text": "Your Lego Millennium Falcon gift is on its way.",
        },
    )
    delivery = {"shop": shop, "date": day, "status": status}
    s.primary.queue_structured(
        {"results": [{**verdict(email, category, f"{shop} parcel"), "delivery": delivery}]}
    )
    await s.run_periodic("email.triage")


async def get(s: Scenario, path: str) -> httpx.Response:
    async with web_client(s) as client:
        await frame(s, client)
        return await client.get(path, headers={"HX-Request": "true"})


async def note(s: Scenario) -> str:
    return words((await get(s, "/wall/part/note")).text)


async def test_a_parcel_due_today_is_themis_note(mail: Scenario) -> None:
    await shipping(mail, "Chewy", "out_for_delivery")
    assert "A delivery from Chewy is due today." in await note(mail)
    view = words((await get(mail, "/wall/view/note")).text)
    assert "Why this note: A shipping email says it&#39;s expected today." in view
    assert "Got it" in view
    page = (await get(mail, "/wall")).text
    assert "Lego" not in page and "Falcon" not in page  # never what's in it


async def test_once_delivered_it_says_it_may_be_at_the_door(mail: Scenario) -> None:
    await shipping(mail, "Chewy", "out_for_delivery")
    await shipping(mail, "Chewy", "delivered", category="confirmation")
    assert "A delivery from Chewy came today. It may be at the door." in await note(mail)


async def test_several_shops_are_one_line(mail: Scenario) -> None:
    await shipping(mail, "Chewy", "on_the_way")
    await shipping(mail, "Amazon", "out_for_delivery")
    assert "Deliveries from Amazon and Chewy are due today." in await note(mail)


async def test_a_door_parcel_comes_before_a_chore_and_a_due_one_after(mail: Scenario) -> None:
    yesterday = mail.today() - timedelta(days=1)
    await task(mail, "Erin", "Bring bins in", due=yesterday, chore=True, both="either")
    await shipping(mail, "Chewy", "on_the_way")
    assert "Bring bins in is still waiting" in await note(mail)
    await shipping(mail, "Amazon", "delivered")
    assert "A delivery from Amazon came today." in await note(mail)


async def test_other_days_and_undated_parcels_arent_today(mail: Scenario) -> None:
    await shipping(mail, "Chewy", "on_the_way", day="2026-10-23")
    await shipping(mail, "Amazon", "on_the_way", day="")
    assert "delivery" not in (await note(mail)).lower()
    found = mail.app.services.get(keys.deliveries)
    assert [d.shop for d in found.on(mail.today() + timedelta(days=2))] == ["Chewy"]


async def test_an_undated_out_for_delivery_counts_for_the_day_it_came(mail: Scenario) -> None:
    await shipping(mail, "Chewy", "out_for_delivery", day="")
    assert "A delivery from Chewy is due today." in await note(mail)


async def test_got_it_quiets_the_note(mail: Scenario) -> None:
    await shipping(mail, "Chewy", "out_for_delivery")
    async with web_client(mail) as client:
        await frame(mail, client)
        page = await client.get("/wall")
        csrf = re.search(r'"X-CSRF-Token": "([^"]+)"', page.text)
        assert csrf
        await client.post(
            "/wall/view/note",
            data={"answer": "ok"},
            headers={"X-CSRF-Token": csrf[1], "HX-Request": "true"},
        )
    assert "delivery" not in (await note(mail)).lower()
    await shipping(mail, "Chewy", "delivered")  # news: it's at the door now
    assert "came today" in await note(mail)


async def test_the_household_can_turn_parcel_notes_off(mail: Scenario) -> None:
    mail.app.store.save_household(mail.member("Erin"), WallSettings, deliveries=False)
    await shipping(mail, "Chewy", "out_for_delivery")
    assert "delivery" not in (await note(mail)).lower()


async def test_an_email_about_no_parcel_keeps_nothing(mail: Scenario) -> None:
    inbox: FakeGmail = mail.gmail  # type: ignore[assignment]
    [email] = await arrive(
        mail, inbox, {"sender": "A <a@x.example>", "subject": "Hi", "text": "Hi"}
    )
    item: dict[str, Any] = {**verdict(email, "routine"), "delivery": NO_DELIVERY}
    mail.primary.queue_structured({"results": [item]})
    await mail.run_periodic("email.triage")
    assert mail.app.db.scalar("SELECT COUNT(*) FROM deliveries") == 0
