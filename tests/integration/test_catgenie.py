"""CG1a: the CatGenie connector against the fake: signing in by text code, tokens, reads,
notifications, a sign-in that stops working, the edge's empty answers, and captures."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fakes.catgenie import CODE, PHONE, FakeCatGenie
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.cli import main
from themi.connectors.catgenie import (
    ALERT,
    ERROR,
    LOW,
    OUT,
    SOLUTION,
    BadCode,
    CatGenieAccount,
    CatGenieError,
    CatGenieWatcher,
    LitterBoxEvent,
)
from themi.connectors.catgenie.client import normal_phone
from themi.connectors.catgenie.watch import write_captures

pytestmark = pytest.mark.usefixtures("frozen_clock")

BOX, UPSTAIRS = "CGR0000001", "CGR0000002"


def watcher_for(family: SeededFamily, fake: FakeCatGenie) -> CatGenieWatcher:
    return CatGenieWatcher(
        family.store, CatGenieAccount(family.db, family.store.cipher, fake.config())
    )


def heard(watcher: CatGenieWatcher) -> list[LitterBoxEvent]:
    events: list[LitterBoxEvent] = []

    async def listen(event: LitterBoxEvent) -> None:
        events.append(event)

    watcher.listeners.append(listen)
    return events


def state(watcher: CatGenieWatcher, external_id: str = BOX) -> str | None:
    device = next(d for d in watcher.devices() if d.external_id == external_id)
    return watcher.states().get(device.id)


@pytest.fixture
def boxes(fake_catgenie: FakeCatGenie) -> FakeCatGenie:
    fake_catgenie.add_box(BOX, "CatGenie")
    return fake_catgenie


@pytest.fixture
async def linked(family: SeededFamily, boxes: FakeCatGenie) -> CatGenieWatcher:
    watcher = watcher_for(family, boxes)
    await watcher.send_code(PHONE)
    await watcher.link(family.erin, PHONE, CODE)
    return watcher


def test_phone_numbers_as_people_type_them() -> None:
    assert normal_phone("+1 (555) 010-0123") == PHONE
    assert normal_phone("555-010-0123") == PHONE  # ten digits: a US number
    assert normal_phone("1 555 010 0123") == PHONE
    assert normal_phone("+44 7700 900123") == "+447700900123"
    with pytest.raises(CatGenieError, match="country code"):
        normal_phone("0100123")


async def test_signing_in_by_text_keeps_the_sign_in_encrypted_and_not_the_number(
    family: SeededFamily, boxes: FakeCatGenie
) -> None:
    boxes.add_box(UPSTAIRS, "Upstairs CatGenie")
    watcher = watcher_for(family, boxes)
    assert await watcher.send_code("(555) 010-0123") == PHONE
    assert boxes.codes_sent == [PHONE]
    added = await watcher.link(family.erin, "555 010 0123", f" {CODE} ")
    assert [(d.provider, d.external_id, d.name, d.appliance) for d in added] == [
        ("catgenie", BOX, "CatGenie", "litter_box"),
        ("catgenie", UPSTAIRS, "Upstairs CatGenie", "litter_box"),
    ]
    row = family.db.one("SELECT * FROM catgenie_account")
    assert row is not None
    (refresh,) = boxes.refresh_tokens
    assert refresh.encode() not in bytes(row["refresh_token"])
    assert family.store.cipher.decrypt(row["refresh_token"]).reveal() == refresh
    # The number was only for signing in: nothing in the database has it.
    for table in family.db.query("SELECT name FROM sqlite_master WHERE type = 'table'"):
        for stored in family.db.query(f"SELECT * FROM {table['name']}"):
            assert "5550100123" not in json.dumps(stored, default=str)
    # Linking again adds nothing new.
    await watcher.send_code(PHONE)
    assert await watcher.link(family.erin, PHONE, CODE) == []


async def test_a_wrong_code_keeps_nothing(family: SeededFamily, boxes: FakeCatGenie) -> None:
    watcher = watcher_for(family, boxes)
    await watcher.send_code(PHONE)
    with pytest.raises(BadCode, match="Ask for a new one"):
        await watcher.link(family.erin, PHONE, "000000")
    with pytest.raises(BadCode):
        await watcher.link(family.erin, PHONE, "")
    assert not watcher.account.linked() and watcher.devices() == []


async def test_tokens_are_renewed_before_they_end_and_after_a_401(
    linked: CatGenieWatcher, boxes: FakeCatGenie
) -> None:
    def renewals() -> int:
        return boxes.calls.count("POST facade/v1/mobile-user/refreshToken/v2")

    await linked.poll()
    assert renewals() == 0  # signing in gave a token
    clock.advance(timedelta(minutes=29))  # nearly its 30 minutes: renewed first
    await linked.poll()
    assert renewals() == 1
    boxes.expire_tokens()  # ended early: a 401, renewed, and the call again
    clock.advance(timedelta(minutes=10))
    assert await linked.poll() == 0
    assert renewals() == 2
    assert state(linked) == "ready, 39% sani-solution left"


async def test_a_new_refresh_token_is_kept(
    family: SeededFamily, linked: CatGenieWatcher, boxes: FakeCatGenie
) -> None:
    boxes.rotate = True  # a renewal hands back another refresh token, and the old one ends
    (old,) = boxes.refresh_tokens
    clock.advance(timedelta(minutes=29))
    await linked.poll()
    (new,) = boxes.refresh_tokens
    assert new != old
    row = family.db.one("SELECT refresh_token FROM catgenie_account")
    assert row is not None and family.store.cipher.decrypt(row["refresh_token"]).reveal() == new
    await linked.account.close()  # as after a restart: signed in again from what was kept
    boxes.expire_tokens()
    assert await linked.poll() == 0
    assert linked.account.problem() is None


async def test_a_refused_sign_in_tells_the_admins_once_and_stops_calling(
    family: SeededFamily, linked: CatGenieWatcher, boxes: FakeCatGenie
) -> None:
    told: list[str] = []

    async def tell(why: str) -> None:
        told.append(why)

    linked.broken_listeners.append(tell)
    await linked.poll()
    boxes.revoke()
    clock.advance(timedelta(minutes=10))
    assert await linked.poll() == 0
    assert await linked.poll() == 0
    assert len(told) == 1 and "Link the litter box again" in told[0]
    assert linked.account.problem() == told[0]
    calls = len(boxes.calls)
    await linked.poll()
    assert len(boxes.calls) == calls  # broken: no calls until it's linked again
    await linked.send_code(PHONE)
    await linked.link(family.erin, PHONE, CODE)
    assert linked.account.problem() is None


async def test_an_empty_answer_or_an_outage_is_a_failure_never_an_empty_account(
    linked: CatGenieWatcher, boxes: FakeCatGenie, caplog: pytest.LogCaptureFixture
) -> None:
    events = heard(linked)
    await linked.poll()
    boxes.set(BOX, sani=0)
    boxes.filter(times=1)  # the edge's empty 200
    with caplog.at_level(logging.WARNING):
        assert await linked.poll() == 0
    assert "answered with nothing" in caplog.text
    assert state(linked) == "ready, 39% sani-solution left"  # as it was, not changed
    boxes.fail(times=1)
    assert await linked.poll() == 0
    device = linked.devices()[0]
    boxes.filter(times=1)
    with pytest.raises(CatGenieError, match="answered with nothing"):
        await linked.read(device)
    assert events == []
    assert await linked.poll() == 1  # and read again when it answers
    assert linked.account.problem() is None


async def test_the_first_read_is_the_starting_point_then_changes_are_events(
    linked: CatGenieWatcher, boxes: FakeCatGenie
) -> None:
    events = heard(linked)
    boxes.set(BOX, sani=15)
    assert await linked.poll() == 0  # low already when linked: nothing announced
    assert state(linked) == "ready, 15% sani-solution left"
    boxes.set(BOX, sani=0, error="HEATER_FAULT", cleaning=40)
    assert await linked.poll() == 2
    assert state(linked) == (
        "cleaning (40% done), 0% sani-solution left; it shows an error (heater fault)"
    )
    assert [(e.kind, e.detail, e.gone) for e in events] == [
        (ERROR, "it shows an error (heater fault)", False),
        (SOLUTION, OUT, False),  # worse words for the same problem
    ]
    boxes.set(BOX, sani=100, error="", cleaning=-1)  # a new cartridge, the error gone
    assert await linked.poll() == 2
    assert [(e.kind, e.gone) for e in events[2:]] == [(ERROR, True), (SOLUTION, True)]
    assert await linked.poll() == 0  # nothing changed


async def test_active_errors_of_any_shape_are_problems(
    linked: CatGenieWatcher, boxes: FakeCatGenie
) -> None:
    events = heard(linked)
    await linked.poll()
    boxes.set(BOX, active_errors=[{"errorType": "DOME_OPEN"}, "WATER_LEVEL", {"x": 1}])
    await linked.poll()
    assert events[0].kind == ERROR
    assert events[0].detail == (
        "it shows an error (dome open); it shows an error (water level); "
        'it shows an error ({"x": 1})'
    )


async def test_an_alert_naming_an_error_lasts_until_the_box_cleans_again(
    linked: CatGenieWatcher, boxes: FakeCatGenie
) -> None:
    events = heard(linked)
    boxes.alert(BOX, "OLD_ERROR", clock.now() - timedelta(days=2))  # before linking
    await linked.poll()  # the starting point: old alerts are kept, not raised
    assert events == []
    boxes.alert(BOX, "", clock.now())  # a notification that isn't an error
    clock.advance(timedelta(minutes=10))
    assert await linked.poll() == 0
    boxes.alert(BOX, "DOME_OPEN", clock.now())
    clock.advance(timedelta(minutes=10))
    assert await linked.poll() == 1
    assert (events[0].kind, events[0].detail) == (ALERT, "it shows an error (dome open)")
    clock.advance(timedelta(minutes=10))
    assert await linked.poll() == 0  # still live: it hasn't cleaned since
    boxes.clean(BOX, clock.now())
    clock.advance(timedelta(minutes=10))
    assert await linked.poll() == 1
    assert (events[-1].kind, events[-1].gone) == (ALERT, True)
    assert linked.db.scalar("SELECT COUNT(*) FROM catgenie_notifications") == 3


async def test_notifications_failing_still_read_the_box(
    linked: CatGenieWatcher, boxes: FakeCatGenie
) -> None:
    await linked.poll()
    boxes.set(BOX, sani=10)
    real = linked.account.notifications

    async def down() -> list[dict[str, object]]:
        raise CatGenieError("PetNovations answered 503")

    linked.account.notifications = down  # type: ignore[method-assign]
    assert await linked.poll() == 1
    linked.account.notifications = real  # type: ignore[method-assign]
    assert state(linked) == "ready, 10% sani-solution left"


async def test_read_now_keeps_the_report(linked: CatGenieWatcher, boxes: FakeCatGenie) -> None:
    device = linked.devices()[0]
    boxes.set(BOX, sani=15)
    reading = await linked.read(device)
    assert reading.problems == {SOLUTION: LOW}
    assert reading.cycles == 600
    raw = linked.raw(device)
    assert raw is not None and raw["remainingSaniSolution"] == 15
    assert state(linked) == "ready, 15% sani-solution left"


async def test_capture_leaves_out_ids_names_and_numbers(
    linked: CatGenieWatcher, boxes: FakeCatGenie, tmp_path: Path
) -> None:
    boxes.set(BOX, error="HEATER_FAULT")
    boxes.alert(BOX, "DOME_OPEN", clock.now())
    path = await write_captures(linked, tmp_path / "captured")
    text = path.read_text()
    assert BOX not in text and 'CatGenie"' not in text and "000000000001" not in text
    saved = json.loads(text)
    (box,) = saved["devices"]
    assert box["report"]["remainingSaniSolution"] == 39
    assert box["reading"]["unknown"] == ["HEATER_FAULT"]
    assert saved["notifications"][0]["data"]["errorType"] == "DOME_OPEN"
    assert "parentDeviceId" not in saved["notifications"][0]["data"]


def test_the_capture_command_needs_catgenie_linked(
    family: SeededFamily, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import themi.cli as cli

    monkeypatch.setattr(cli, "_store", lambda: family.store)
    assert main(["catgenie", "capture"]) == 1
    assert "Link the litter box on the website's Accounts page first." in capsys.readouterr().err
