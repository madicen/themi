"""PT3: the carriers' own emails join the shops' parcels by tracking number. Erin's inbox
is linked and watched; Wednesday 21 October 2026, Los Angeles (as in WL8's scenario)."""

from __future__ import annotations

from pathlib import Path

from tests.fakes.gmail_api import FakeGmail
from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import arrive, verdict
from tests.scenarios.test_wall_deliveries import mail, note  # noqa: F401  (the fixture)
from themi.core import keys

FIXTURES = Path(__file__).parents[1] / "fixtures" / "parcels"
UPS = "1Z5R89390357567127"


def parcel(shop: str, status: str, tracking: str, day: str = "", window: str = "") -> dict:
    return {
        "shop": shop,
        "tracking": tracking,
        "date": day,
        "status": status,
        "problem": "",
        "window": window,
    }


async def sorted_as(s: Scenario, mail_: dict, *parcels: dict) -> None:
    inbox: FakeGmail = s.gmail  # type: ignore[assignment]
    [email] = await arrive(s, inbox, mail_)
    s.primary.queue_structured(
        {"results": [{**verdict(email, "routine", "parcels"), "parcels": list(parcels)}]}
    )
    await s.run_periodic("email.triage")


async def test_ups_my_choice_joins_chewys_parcel_with_its_window(mail: Scenario) -> None:  # noqa: F811
    await sorted_as(
        mail,
        {
            "sender": "Chewy <orders@chewy.com>",
            "subject": "Your order has shipped",
            "text": f"Your order has shipped.\nUPS tracking number: {UPS}",
        },
        parcel("Chewy", "on_the_way", UPS, "2026-10-23"),
    )
    await sorted_as(
        mail,
        {
            "sender": "UPS <mcinfo@ups.com>",
            "subject": "Your UPS Package is out for delivery",
            "html": (FIXTURES / "ups_my_choice.html").read_text(),
        },
        parcel("UPS", "out_for_delivery", UPS, "2026-10-21", "14:15-16:15"),
    )
    [kept] = mail.app.services.get(keys.deliveries).parcels()
    assert (kept.shop, kept.status, kept.number, kept.carrier) == (
        "Chewy",
        "out_for_delivery",
        UPS,
        "ups",
    )
    assert (kept.window_start, kept.window_end) == ("14:15", "16:15")
    assert "A delivery from Chewy is due today." in await note(mail)


async def test_informed_deliverys_digest_is_a_parcel_each(mail: Scenario) -> None:  # noqa: F811
    numbers = ("9400111206206406260787", "9405803699300124287899", "9434611206206406227577")
    await sorted_as(
        mail,
        {
            "sender": "USPS Informed Delivery <USPSInformeddelivery@usps.com>",
            "subject": "Your Daily Digest",
            "html": (FIXTURES / "informed_delivery.html").read_text(),
        },
        parcel("Chewy", "out_for_delivery", numbers[0], "2026-10-21"),
        parcel("USPS", "on_the_way", numbers[1], "2026-10-23"),
        parcel("Etsy seller", "on_the_way", numbers[2], "2026-10-23"),
    )
    kept = mail.app.services.get(keys.deliveries).parcels()
    assert [(p.shop, p.number, p.carrier) for p in kept] == [
        ("Chewy", numbers[0], "usps"),
        ("USPS", numbers[1], "usps"),
        ("Etsy seller", numbers[2], "usps"),
    ]


async def test_the_parcels_page_has_the_sign_up_guide(mail: Scenario) -> None:  # noqa: F811
    async with web_client(mail) as site:
        await sign_in(mail, site, "Erin")
        page = (await site.get("/modules/parcels")).text
    assert "USPS Informed Delivery" in page and "UPS My Choice" in page
    assert "https://www.fedex.com/en-us/delivery-manager.html" in page
    for field in (
        "UPS client ID",
        "UPS client secret",
        "USPS consumer key",
        "USPS consumer secret",
    ):
        assert field in page  # PT4: the carriers' keys
    assert "Ask the carriers about parcels with a tracking number" in page
