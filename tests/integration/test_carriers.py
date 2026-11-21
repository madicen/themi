"""PT4: asking UPS and USPS about a parcel, against the fake carriers (their published
answer shapes, `tests/fixtures/carriers/`)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import pytest

from tests.fakes.carriers import USPS_SECRET, FakeCarriers, fixture
from themi import clock
from themi.connectors.carriers import CarrierError, NotFound, UpsClient, UspsClient
from themi.connectors.carriers import ups as ups_answers
from themi.connectors.carriers import usps as usps_answers
from themi.storage.secrets import Secret
from themi_google.google_settings import ParcelsSettings
from themi_google.parcels import ParcelsModule, carriers_from

UPS = "1Z5R89390357567127"
USPS = "9400111206206406260787"
NOW = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen() -> None:
    clock.freeze(NOW)


def ups(fake: FakeCarriers) -> UpsClient:
    return fake.clients()["ups"]


def usps(fake: FakeCarriers) -> UspsClient:
    return fake.clients()["usps"]


# ----- UPS --------------------------------------------------------------------------------


async def test_ups_on_its_way(fake_carriers: FakeCarriers) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    found = await ups(fake_carriers).track(UPS)
    assert (found.status, found.expected_day) == ("on_the_way", date(2026, 10, 23))
    assert (found.window_start, found.window_end) == ("", "")  # end of day is no window
    assert found.last_event_at == datetime(2026, 10, 20, 22, 15, tzinfo=UTC) - timedelta(hours=-7)


async def test_ups_out_for_delivery_with_its_window(fake_carriers: FakeCarriers) -> None:
    fake_carriers.answer("ups", UPS, "ups_out_for_delivery")
    found = await ups(fake_carriers).track(UPS)
    assert found.status == "out_for_delivery"
    assert (found.window_start, found.window_end) == ("14:15", "16:15")


async def test_ups_delivered_and_where_it_was_left(fake_carriers: FakeCarriers) -> None:
    fake_carriers.answer("ups", UPS, "ups_delivered")
    found = await ups(fake_carriers).track(UPS)
    assert (found.status, found.left_at) == ("delivered", "Front Door")
    assert found.delivered_at == datetime(2026, 10, 21, 20, 40, tzinfo=UTC)


async def test_ups_exception_is_a_problem_cut_short(fake_carriers: FakeCarriers) -> None:
    fake_carriers.answer("ups", UPS, "ups_exception")
    found = await ups(fake_carriers).track(UPS)
    assert found.status == "problem"
    assert found.problem.startswith("The receiver was not available") and len(found.problem) == 80
    assert found.expected_day == date(2026, 10, 22)  # rescheduled
    assert found.signature


def test_an_unknown_ups_status_type_is_on_its_way(caplog: pytest.LogCaptureFixture) -> None:
    answer = fixture("ups_in_transit", UPS)
    answer["trackResponse"]["shipment"][0]["package"][0]["currentStatus"]["type"] = "Q"
    with caplog.at_level(logging.INFO):
        assert ups_answers.tracking_from(answer).status == "on_the_way"
    assert "UPS status type 'Q'" in caplog.text


async def test_ups_doesnt_know_the_number(fake_carriers: FakeCarriers) -> None:
    with pytest.raises(NotFound):
        await ups(fake_carriers).track(UPS)


# ----- USPS -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "status", "day"),
    [
        ("usps_in_transit", "on_the_way", date(2026, 10, 23)),
        ("usps_out_for_delivery", "out_for_delivery", date(2026, 10, 21)),
        ("usps_delivered", "delivered", date(2026, 10, 21)),
        ("usps_alert", "problem", None),
    ],
)
async def test_usps_statuses(
    fake_carriers: FakeCarriers, name: str, status: str, day: date | None
) -> None:
    fake_carriers.answer("usps", USPS, name)
    found = await usps(fake_carriers).track(USPS)
    assert (found.status, found.expected_day) == (status, day)


async def test_usps_window_where_left_and_problem(fake_carriers: FakeCarriers) -> None:
    client = usps(fake_carriers)
    fake_carriers.answer("usps", USPS, "usps_out_for_delivery")
    found = await client.track(USPS)
    assert (found.window_start, found.window_end) == ("10:00", "14:00")
    fake_carriers.answer("usps", USPS, "usps_delivered")
    found = await client.track(USPS)
    assert found.left_at == "Front Door/Porch"
    assert found.delivered_at == datetime(2026, 10, 21, 20, 40, tzinfo=UTC)
    fake_carriers.answer("usps", USPS, "usps_alert")
    found = await client.track(USPS)
    assert found.problem == "Notice Left (No Authorized Recipient Available)" and found.signature


def test_an_unknown_usps_category_is_on_its_way(caplog: pytest.LogCaptureFixture) -> None:
    [answer] = fixture("usps_in_transit", USPS)
    answer["statusCategory"] = "Something New"
    with caplog.at_level(logging.INFO):
        assert usps_answers.tracking_from(answer).status == "on_the_way"
    assert "USPS status category 'something new'" in caplog.text


async def test_usps_doesnt_know_the_number(fake_carriers: FakeCarriers) -> None:
    with pytest.raises(NotFound):
        await usps(fake_carriers).track(USPS)


# ----- tokens and errors ------------------------------------------------------------------


async def test_a_token_is_kept_until_it_runs_out(fake_carriers: FakeCarriers) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    client = ups(fake_carriers)
    await client.track(UPS)
    await client.track(UPS)
    assert fake_carriers.tokens["ups"] == 1
    clock.advance(timedelta(minutes=59))  # within two minutes of its hour
    await client.track(UPS)
    assert fake_carriers.tokens["ups"] == 2


async def test_a_401_gets_a_new_token_once(fake_carriers: FakeCarriers) -> None:
    fake_carriers.answer("usps", USPS, "usps_in_transit")
    client = usps(fake_carriers)
    await client.track(USPS)
    fake_carriers.revoke("usps")
    assert (await client.track(USPS)).status == "on_the_way"
    assert fake_carriers.tokens["usps"] == 2


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_refusal_or_an_outage_is_a_carrier_error(
    fake_carriers: FakeCarriers, status: int
) -> None:
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    client = ups(fake_carriers)
    await client.check()
    fake_carriers.fail("ups", status)
    with pytest.raises(CarrierError, match=str(status)):
        await client.track(UPS)
    assert (await client.track(UPS)).status == "on_the_way"  # next time it answers


async def test_a_timeout_is_a_carrier_error(fake_carriers: FakeCarriers) -> None:
    fake_carriers.timeout("usps")
    with pytest.raises(CarrierError, match="ReadTimeout"):
        await usps(fake_carriers).track(USPS)


async def test_wrong_keys_are_turned_down(fake_carriers: FakeCarriers) -> None:
    transport = fake_carriers.transport("usps")
    client = UspsClient(
        "usps-key", Secret("wrong"), base_url="https://usps.fake", transport=transport
    )
    with pytest.raises(CarrierError, match="turned the consumer key and secret down"):
        await client.check()


async def test_calls_are_counted(fake_carriers: FakeCarriers) -> None:
    seen: list[int | None] = []
    client = ups(fake_carriers)
    client.tally = lambda status=None, n=1: seen.append(status)  # type: ignore[assignment]
    fake_carriers.answer("ups", UPS, "ups_in_transit")
    await client.track(UPS)
    fake_carriers.fail("ups", 429)
    with pytest.raises(CarrierError):
        await client.track(UPS)
    assert seen == [200, 200, 429]  # the token, the lookup, the refusal


async def test_only_the_number_is_sent(fake_carriers: FakeCarriers) -> None:
    fake_carriers.answer("usps", USPS, "usps_in_transit")
    await usps(fake_carriers).track(USPS)
    assert fake_carriers.requests == [("usps", USPS)]


# ----- the module -------------------------------------------------------------------------


async def test_test_asks_each_carrier_for_a_token(fake_carriers: FakeCarriers) -> None:
    module = ParcelsModule(fake_carriers.clients())
    assert await module.check() is None
    fake_carriers.fail("usps", 401)
    assert await module.check() == "USPS: USPS turned the consumer key and secret down"


async def test_test_without_keys_says_so() -> None:
    assert "No carrier keys yet" in (await ParcelsModule().check() or "")


def test_keys_go_in_pairs_and_build_their_carriers() -> None:
    with pytest.raises(ValueError, match="UPS_CLIENT_ID and UPS_CLIENT_SECRET go together"):
        ParcelsSettings(ups_client_id="x")
    settings = ParcelsSettings(usps_consumer_key="k", usps_consumer_secret=Secret("s"))
    assert list(carriers_from(settings)) == ["usps"]
    assert carriers_from(ParcelsSettings()) == {}


async def test_secrets_never_reach_the_logs(
    fake_carriers: FakeCarriers, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        fake_carriers.fail("usps", 401)
        with pytest.raises(CarrierError):
            await usps(fake_carriers).check()
        settings = ParcelsSettings(usps_consumer_key="k", usps_consumer_secret=Secret(USPS_SECRET))
        logging.getLogger("test").info("settings: %s", settings)
    assert USPS_SECRET not in caplog.text
