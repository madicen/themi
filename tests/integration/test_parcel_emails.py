"""PT3: the carriers' alert emails and the shops' shipping emails, from the fixtures in
`tests/fixtures/parcels/` (see its README for what each is)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from themi.modules.guides import guide
from themi_google.connectors.gmail.parse import parse_message
from themi_google.parcels import ParcelsModule
from themi_google.tracking import Found
from themi_google.triage import SYSTEM

FIXTURES = Path(__file__).parents[1] / "fixtures" / "parcels"


def message(name: str, sender: str) -> dict:
    body = (FIXTURES / name).read_text(encoding="utf-8")
    mime = "text/html" if name.endswith(".html") else "text/plain"
    data = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX"],
        "snippet": "",
        "internalDate": "1792900000000",
        "payload": {
            "mimeType": mime,
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": "x"}],
            "body": {"data": data},
        },
    }


@pytest.mark.parametrize(
    ("name", "sender", "found"),
    [
        (
            "informed_delivery.html",
            "USPS Informed Delivery <USPSInformeddelivery@email.informeddelivery.usps.com>",
            [
                Found("usps", "9400111206206406260787"),
                Found("usps", "9405803699300124287899"),
                Found("usps", "9434611206206406227577"),
            ],
        ),
        ("ups_my_choice.html", "UPS <mcinfo@ups.com>", [Found("ups", "1Z5R89390357567127")]),
        (
            "fedex_delivery_manager.html",
            "FedEx Delivery Manager <TrackingUpdates@fedex.com>",
            [Found("fedex", "986578788855")],
        ),
        (
            "amazon_shipped.html",
            "Amazon.com <shipment-tracking@amazon.com>",
            [Found("amazon", "TBA502887274000")],
        ),
        (
            "shopify_shipped.html",
            "Moss & Fern <store+1234@t.shopifyemail.com>",
            [Found("fedex", "477179081230")],
        ),
        ("chewy_shipped.txt", "Chewy <orders@chewy.com>", [Found("ups", "1Z879E930346834440")]),
    ],
)
def test_each_fixtures_tracking_numbers(name: str, sender: str, found: list[Found]) -> None:
    assert list(parse_message(message(name, sender)).tracking) == found


def test_order_numbers_in_the_fixtures_are_not_tracking_numbers() -> None:
    parsed = parse_message(message("amazon_shipped.html", "Amazon <a@amazon.com>"))
    assert all("113" not in f.number for f in parsed.tracking)


def test_triage_is_told_about_the_carriers_emails() -> None:
    words = " ".join(SYSTEM.split())
    assert "USPS Informed Delivery's digest" in words
    assert "list each package it names" in words
    assert 'or the carrier ("USPS") when it names none' in words


def test_the_guide_links_each_service_and_asks_for_no_password() -> None:
    text = guide(ParcelsModule)
    assert text is not None
    for link in (
        "https://informeddelivery.usps.com",
        "https://www.ups.com/mychoice",
        "https://www.fedex.com/en-us/delivery-manager.html",
    ):
        assert f"]({link})" in text
    assert "never needs your passwords" in text
    assert ParcelsModule.requires == ("email_triage",)
