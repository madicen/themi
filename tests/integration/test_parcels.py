"""PT2: one parcel per tracking number, fed by every email that names it."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tests.fakes.modules import bare_services
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.storage import migrations
from themi.storage.db import Database
from themi_google.deliveries import Deliveries, Fact
from themi_google.tracking import Found, as_json
from themi_google.triage import Verdict

NOW = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)  # 9 am in Los Angeles, Wednesday
TODAY = date(2026, 10, 21)
FRIDAY = date(2026, 10, 23)
UPS = "1Z5R89390357567127"
UPS_2 = "1Z879E930346834440"


@pytest.fixture
def parcels(family: SeededFamily) -> Deliveries:
    clock.freeze(NOW)
    return Deliveries(bare_services(family.store))


def fact(shop: str, status: str, hours: float = 0, **kw: object) -> Fact:
    return Fact(shop=shop, status=status, at=NOW + timedelta(hours=hours), **kw)  # type: ignore[arg-type]


def test_a_shop_email_and_a_carrier_email_are_one_parcel(
    parcels: Deliveries, family: SeededFamily
) -> None:
    erin = family.erin.id
    parcels.record(
        erin, fact("Chewy", "on_the_way", -20, number=UPS, carriers=("ups",), day=FRIDAY)
    )
    parcels.record(erin, fact("UPS", "out_for_delivery", 0, number=UPS, carriers=("ups",)))
    [kept] = parcels.parcels()
    assert (kept.shop, kept.status, kept.carrier, kept.number) == (
        "Chewy",
        "out_for_delivery",
        "ups",
        UPS,
    )
    assert kept.expected_day == TODAY  # an undated "out for delivery" is today


def test_a_carriers_name_gives_way_to_the_shops(parcels: Deliveries, family: SeededFamily) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("USPS", "on_the_way", -5, number=UPS, day=FRIDAY))
    parcels.record(erin, fact("Chewy", "on_the_way", -10, number=UPS))  # older, but a shop
    assert [p.shop for p in parcels.parcels()] == ["Chewy"]


def test_the_newest_fact_wins_and_delivered_stays(
    parcels: Deliveries, family: SeededFamily
) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Chewy", "delivered", 2, number=UPS))
    parcels.record(erin, fact("Chewy", "out_for_delivery", 1, number=UPS))  # older
    parcels.record(erin, fact("Chewy", "on_the_way", 3, number=UPS))  # newer, but went back
    [kept] = parcels.parcels()
    assert kept.status == "delivered"
    assert kept.delivered_at == NOW + timedelta(hours=2)


def test_an_older_fact_fills_a_blank_day(parcels: Deliveries, family: SeededFamily) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Chewy", "on_the_way", 1, number=UPS))
    parcels.record(erin, fact("Chewy", "on_the_way", 0, number=UPS, day=FRIDAY))
    assert parcels.parcels()[0].expected_day == FRIDAY


def test_a_numberless_email_joins_the_shops_parcel_nearby(
    parcels: Deliveries, family: SeededFamily
) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Chewy", "on_the_way", -20, number=UPS, day=FRIDAY))
    parcels.record(erin, fact("Chewy", "delivered", 0))  # two days early, no number
    [kept] = parcels.parcels()
    assert (kept.number, kept.status, kept.expected_day) == (UPS, "delivered", TODAY)


def test_a_numbered_parcel_takes_in_a_numberless_one_on_its_day(
    parcels: Deliveries, family: SeededFamily
) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Chewy", "out_for_delivery", -1))  # numberless, today
    parcels.record(erin, fact("UPS", "on_the_way", -3, number=UPS, day=TODAY))
    [kept] = parcels.parcels()
    assert (kept.number, kept.shop, kept.status) == (UPS, "Chewy", "out_for_delivery")


def test_an_undated_on_its_way_without_a_number_is_left_out(
    parcels: Deliveries, family: SeededFamily
) -> None:
    assert parcels.record(family.erin.id, fact("Chewy", "on_the_way")) is None
    assert parcels.parcels() == []


def test_an_undated_email_about_one_of_several_joins_neither(
    parcels: Deliveries, family: SeededFamily
) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Amazon", "on_the_way", -2, number="TBA000000000001", day=TODAY))
    parcels.record(erin, fact("Amazon", "on_the_way", -2, number="TBA000000000002", day=FRIDAY))
    assert parcels.record(erin, fact("Amazon", "on_the_way")) is None
    assert [p.status for p in parcels.parcels()] == ["on_the_way", "on_the_way"]


def test_two_carriers_are_kept_until_one_is_named(
    parcels: Deliveries, family: SeededFamily
) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Chewy", "on_the_way", -1, number="123", carriers=("fedex", "usps")))
    assert parcels.parcels()[0].carriers == ["fedex", "usps"]
    parcels.record(erin, fact("Chewy", "on_the_way", 0, number="123", carriers=("usps",)))
    assert parcels.parcels()[0].carriers == ["usps"]


def test_a_line_per_parcel_on_a_day(parcels: Deliveries, family: SeededFamily) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Chewy", "on_the_way", -1, number=UPS, day=TODAY))
    parcels.record(erin, fact("Amazon", "on_the_way", -1, number=UPS_2, day=TODAY))
    parcels.record(erin, fact("Amazon", "out_for_delivery", -1, number="TBA000000000001"))
    parcels.record(erin, fact("Zappos", "on_the_way", -1, number="TBA000000000002", day=FRIDAY))
    assert [(d.shop, d.status) for d in parcels.on(TODAY)] == [
        ("Amazon", "on_the_way"),
        ("Amazon", "out_for_delivery"),
        ("Chewy", "on_the_way"),
    ]


def test_old_parcels_go(parcels: Deliveries, family: SeededFamily) -> None:
    erin = family.erin.id
    parcels.record(erin, fact("Chewy", "delivered", 0, number=UPS))
    parcels.record(erin, fact("Amazon", "on_the_way", 0, number=UPS_2))
    clock.advance(timedelta(days=15))
    parcels.record(erin, fact("Zappos", "on_the_way", 15 * 24, number="TBA000000000001"))
    assert [p.shop for p in parcels.parcels()] == ["Amazon", "Zappos"]
    clock.advance(timedelta(days=16))
    parcels.record(erin, fact("Zappos", "on_the_way", 31 * 24, number="TBA000000000001"))
    assert [p.shop for p in parcels.parcels()] == ["Zappos"]


# ----- from triage's verdicts ---------------------------------------------------------------


def email(tracking: list[Found], hours: float = 0) -> dict:
    return {
        "id": 1,
        "tracking": as_json(tracking),
        "received_at": (NOW + timedelta(hours=hours)).isoformat(),
    }


def parcel(shop: str, status: str, tracking: str = "", day: str = "") -> dict[str, str]:
    return {"shop": shop, "tracking": tracking, "date": day, "status": status, "problem": ""}


async def test_a_verdicts_parcels_are_kept(parcels: Deliveries, family: SeededFamily) -> None:
    found = [Found("ups", UPS), Found("ups", UPS_2)]
    verdict = Verdict(
        1,
        "routine",
        None,
        False,
        "Two parcels",
        "",
        parcels=(
            parcel("Chewy", "on_the_way", UPS, "2026-10-23"),
            parcel("Chewy", "out_for_delivery", UPS_2),
        ),
    )
    await parcels.on_verdict(family.erin, None, email(found), verdict)  # type: ignore[arg-type]
    kept = {p.number: p for p in parcels.parcels()}
    assert kept[UPS].expected_day == FRIDAY and kept[UPS_2].expected_day == TODAY
    assert {p.member_id for p in kept.values()} == {family.erin.id}


async def test_one_parcel_and_one_number_go_together(
    parcels: Deliveries, family: SeededFamily
) -> None:
    verdict = Verdict(1, "routine", None, False, "", "", parcels=(parcel("Chewy", "on_the_way"),))
    await parcels.on_verdict(family.erin, None, email([Found("ups", UPS)]), verdict)  # type: ignore[arg-type]
    assert [(p.number, p.carrier) for p in parcels.parcels()] == [(UPS, "ups")]


async def test_an_email_about_no_parcel_keeps_nothing(
    parcels: Deliveries, family: SeededFamily
) -> None:
    verdict = Verdict(1, "routine", None, False, "", "")
    await parcels.on_verdict(family.erin, None, email([Found("ups", UPS)]), verdict)  # type: ignore[arg-type]
    assert parcels.parcels() == []


# ----- the migration from WL8 -----------------------------------------------------------------


def test_wl8s_rows_become_numberless_parcels(tmp_path: Path) -> None:
    db = Database(tmp_path / "old.db")
    migrations.apply(db, [m for m in migrations.discover() if m.version < 178])
    db.execute("PRAGMA foreign_keys = OFF")
    rows = [
        (1, 1, "Chewy", "2026-10-21", "on_the_way", "2026-10-20T10:00:00+00:00"),
        (2, 1, "chewy", "2026-10-21", "delivered", "2026-10-21T18:00:00+00:00"),
        (3, 2, "Amazon", "2026-10-23", "on_the_way", "2026-10-21T09:00:00+00:00"),
    ]
    for row in rows:
        db.execute(
            "INSERT INTO deliveries (email_id, member_id, shop, day, status, found_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            row,
        )
    migrations.apply(db)
    got = db.query(
        "SELECT member_id, number, shop_key, status, expected_day, updated_at FROM parcels "
        "ORDER BY shop_key"
    )
    assert [tuple(r.values()) for r in got] == [
        (2, "", "amazon", "on_the_way", "2026-10-23", "2026-10-21T09:00:00+00:00"),
        (1, "", "chewy", "delivered", "2026-10-21", "2026-10-21T18:00:00+00:00"),
    ]
    assert not db.one("SELECT name FROM sqlite_master WHERE name = 'deliveries'")
