"""PT5: asking the carriers about parcels on a schedule, with the clock frozen and moved."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.fakes.carriers import FakeCarriers
from tests.fakes.modules import bare_services, module_context
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.modules import Module, ModuleContext
from themi_google.deliveries import Deliveries, Fact
from themi_google.parcel_checks import PER_RUN, ParcelChecks

MORNING = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)  # 9 am Wednesday in Los Angeles
UPS = "1Z5R89390357567127"
USPS = "9400111206206406260787"
FRIDAY = date(2026, 10, 23)
TODAY = date(2026, 10, 21)


@pytest.fixture
def deliveries(family: SeededFamily) -> Deliveries:
    clock.freeze(MORNING)
    return Deliveries(bare_services(family.store))


@pytest.fixture
def checks(deliveries: Deliveries, fake_carriers: FakeCarriers) -> ParcelChecks:
    return ParcelChecks(deliveries, fake_carriers.clients())


def found(
    deliveries: Deliveries,
    family: SeededFamily,
    number: str,
    carriers: tuple[str, ...],
    status: str = "on_the_way",
    day: date | None = FRIDAY,
    shop: str = "Chewy",
) -> None:
    deliveries.record(
        family.erin.id,
        Fact(shop=shop, status=status, at=clock.now(), number=number, carriers=carriers, day=day),
    )


async def run(checks: ParcelChecks, hours: float = 0, minutes: float = 0) -> int:
    clock.advance(timedelta(hours=hours, minutes=minutes))
    return await checks.run()


async def test_a_new_parcel_is_asked_about_then_every_six_hours(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    found(deliveries, family, UPS, ("ups",))
    assert await run(checks) == 1
    assert await run(checks, hours=5, minutes=45) == 0
    assert await run(checks, minutes=15) == 1
    assert fake_carriers.tracked("ups") == [UPS, UPS]


async def test_due_today_or_out_for_delivery_is_hourly_and_a_problem_two_hourly(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_out_for_delivery")
    fake_carriers.answer("usps", USPS, "usps_alert")
    found(deliveries, family, UPS, ("ups",), day=TODAY)
    found(deliveries, family, USPS, ("usps",), shop="Etsy")
    assert await run(checks) == 2
    assert await run(checks, hours=1) == 1  # the one out for delivery
    assert await run(checks, hours=1) == 2  # and the problem, two hours on
    assert fake_carriers.tracked("usps") == [USPS, USPS]


async def test_only_between_seven_and_nine(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    clock.freeze(datetime(2026, 10, 21, 13, 45, tzinfo=UTC))  # 6:45 am
    found(deliveries, family, UPS, ("ups",))
    assert await checks.run() == 0
    assert await run(checks, minutes=15) == 1  # 7 am
    clock.freeze(datetime(2026, 10, 22, 4, 0, tzinfo=UTC))  # 9 pm
    found(deliveries, family, USPS, ("usps",))
    assert await checks.run() == 0


async def test_at_most_twenty_a_run_the_never_asked_first(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    numbers = [f"TEST{n:04d}" for n in range(PER_RUN + 5)]
    for number in numbers:
        found(deliveries, family, number, ("ups",))
    assert await run(checks) == PER_RUN
    assert await run(checks, minutes=15) == 5
    assert sorted(fake_carriers.tracked("ups")) == sorted(numbers)


async def test_an_email_brings_the_next_look_forward(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    found(deliveries, family, UPS, ("ups",))
    await run(checks)
    clock.advance(timedelta(hours=1))
    deliveries.record(  # "shipped" email an hour later
        family.erin.id,
        Fact(shop="Chewy", status="on_the_way", at=clock.now(), number=UPS, carriers=("ups",)),
    )
    assert await run(checks, minutes=15) == 1


async def test_never_asked_delivered_amazon_or_without_keys(
    deliveries: Deliveries, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    checks = ParcelChecks(deliveries, {"usps": fake_carriers.clients()["usps"]})
    found(deliveries, family, "TBA502887274000", ("amazon",))
    found(deliveries, family, UPS, ("ups",))  # no UPS keys
    found(deliveries, family, USPS, ("usps",), status="delivered")
    deliveries.record(
        family.erin.id, Fact(shop="Zappos", status="on_the_way", at=clock.now(), day=FRIDAY)
    )
    assert await checks.run() == 0
    assert fake_carriers.requests == []


async def test_no_news_in_three_weeks_stops_the_looks(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    found(deliveries, family, UPS, ("ups",))
    await run(checks)
    clock.advance(timedelta(days=21, hours=1))
    assert await checks.run() == 0


async def test_a_lookup_updates_the_parcel(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_out_for_delivery")
    found(deliveries, family, UPS, ("ups",))
    await run(checks)
    [parcel] = deliveries.parcels()
    assert (parcel.status, parcel.expected_day, parcel.source) == (
        "out_for_delivery",
        TODAY,
        "lookup",
    )
    assert (parcel.window_start, parcel.window_end, parcel.shop) == ("14:15", "16:15", "Chewy")
    fake_carriers.answer("ups", UPS, "ups_delivered")
    await run(checks, hours=1)
    [parcel] = deliveries.parcels()
    assert (parcel.status, parcel.left_at) == ("delivered", "Front Door")
    await run(checks, hours=1)
    assert len(fake_carriers.tracked("ups")) == 2  # delivered: never again


async def test_an_older_email_doesnt_undo_a_lookup(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_out_for_delivery")
    found(deliveries, family, UPS, ("ups",))
    await run(checks, minutes=30)
    deliveries.record(  # an email sent before the lookup, sorted after it
        family.erin.id,
        Fact(shop="Chewy", status="on_the_way", at=MORNING, number=UPS, carriers=("ups",)),
    )
    assert deliveries.parcels()[0].status == "out_for_delivery"


async def test_a_newer_email_wins_over_an_older_lookup(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_out_for_delivery")
    found(deliveries, family, UPS, ("ups",))
    await run(checks)
    clock.advance(timedelta(minutes=40))
    deliveries.record(
        family.erin.id,
        Fact(shop="Chewy", status="delivered", at=clock.now(), number=UPS, carriers=("ups",)),
    )
    assert deliveries.parcels()[0].status == "delivered"


async def test_nothing_new_keeps_the_no_news_age(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    found(deliveries, family, UPS, ("ups",))
    await run(checks)
    before = deliveries.parcels()[0].updated_at
    await run(checks, hours=6)
    assert deliveries.parcels()[0].updated_at == before


async def test_a_carrier_error_waits_for_the_next_turn(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    found(deliveries, family, UPS, ("ups",))
    fake_carriers.fail("ups", 503)
    assert await run(checks) == 1  # tried, and UPS was down
    assert fake_carriers.tracked("ups") == []
    assert await run(checks, minutes=15) == 0  # not again at once
    assert await run(checks, hours=6) == 1
    assert fake_carriers.tracked("ups") == [UPS]


async def test_two_possible_carriers_are_settled_by_the_one_that_knows_it(
    deliveries: Deliveries, checks: ParcelChecks, family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    fake_carriers.answer("usps", USPS, "usps_in_transit")
    found(deliveries, family, USPS, ("ups", "usps"))
    await run(checks)
    assert deliveries.parcels()[0].carriers == ["usps"]
    assert fake_carriers.tracked("ups") == [USPS] and fake_carriers.tracked("usps") == [USPS]


# ----- the module's job ---------------------------------------------------------------------


class StandInTriage(Module):
    """Email triage's part here: it provides `Deliveries`."""

    name = "email_triage"

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(Deliveries(ctx.services))


def _jobs(family: SeededFamily, module: Module) -> list[str]:
    ctx = module_context(family.store)
    ctx.load(StandInTriage(), module)
    return [job.name for job in ctx.jobs]


def test_the_job_runs_only_with_keys_and_asking_on(
    family: SeededFamily, fake_carriers: FakeCarriers
) -> None:
    from themi_google.google_settings import ParcelsSettings
    from themi_google.parcels import ParcelsModule

    clients = fake_carriers.clients()
    assert "parcels.check" in _jobs(family, ParcelsModule(clients))
    off = ParcelsSettings(ask_carriers=False)
    assert "parcels.check" not in _jobs(family, ParcelsModule(clients, off))
    assert "parcels.check" not in _jobs(family, ParcelsModule({}))
