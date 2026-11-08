"""32: the Tuya connector against the fake: the keys, tokens, discovery, reads and feedings."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fakes.tuya import ACCESS_ID, SECRET, FakeTuya
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.cli import main
from themi_home.connectors.tuya import (
    FOOD,
    LOW,
    OUT,
    FeederEvent,
    KeyRejected,
    RateLimited,
    TuyaAccount,
    TuyaError,
    TuyaWatcher,
)
from themi_home.connectors.tuya.watch import write_captures

pytestmark = pytest.mark.usefixtures("frozen_clock")

FEEDER, FAULTY, FOUNTAIN = "ebfeeder1", "ebfeeder2", "ebfountain3"


def watcher_for(family: SeededFamily, fake: FakeTuya) -> TuyaWatcher:
    return TuyaWatcher(family.store, TuyaAccount(family.db, family.store.cipher, fake.config()))


def heard(watcher: TuyaWatcher) -> list[FeederEvent]:
    events: list[FeederEvent] = []

    async def listen(event: FeederEvent) -> None:
        events.append(event)

    watcher.listeners.append(listen)
    return events


@pytest.fixture
def pets(fake_tuya: FakeTuya) -> FakeTuya:
    fake_tuya.add_feeder(FEEDER, "Cat Feeder")
    fake_tuya.add_feeder(FAULTY, "Mochi's feeder", "fault")
    fake_tuya.add_device(FOUNTAIN, "Water fountain", "cwysj", "pqxfountain003")
    return fake_tuya


@pytest.fixture
async def linked(family: SeededFamily, pets: FakeTuya) -> TuyaWatcher:
    watcher = watcher_for(family, pets)
    await watcher.link(family.erin, ACCESS_ID, SECRET, "us")
    return watcher


async def test_linking_keeps_the_secret_encrypted_and_maps_the_feeders(
    family: SeededFamily, pets: FakeTuya
) -> None:
    watcher = watcher_for(family, pets)
    added = await watcher.link(family.erin, f" {ACCESS_ID} ", f"{SECRET}\n", "us")
    assert [(d.provider, d.external_id, d.name, d.appliance) for d in added] == [
        ("tuya", FEEDER, "Cat Feeder", "feeder"),
        ("tuya", FAULTY, "Mochi's feeder", "feeder"),
        ("tuya", FOUNTAIN, "Water fountain", None),  # not a feeder: left unmapped
    ]
    row = family.db.one("SELECT * FROM tuya_account")
    assert row is not None
    assert row["access_id"] == ACCESS_ID and row["region"] == "us"
    assert SECRET.encode() not in bytes(row["secret"])
    assert family.store.cipher.decrypt(row["secret"]).reveal() == SECRET
    assert "f4k3s3cr3t" not in repr(watcher.account._client_for_row()._secret)
    # Linking again adds nothing new, and keeps the mapping someone changed.
    family.store.set_device_appliance(family.erin, added[2].id, "feeder")
    assert await watcher.link(family.erin, ACCESS_ID, SECRET, "us") == []
    assert [d.appliance for d in watcher.devices()] == ["feeder", "feeder", "feeder"]


async def test_a_wrong_secret_or_place_keeps_nothing(family: SeededFamily, pets: FakeTuya) -> None:
    watcher = watcher_for(family, pets)
    with pytest.raises(KeyRejected):
        await watcher.link(family.erin, ACCESS_ID, "not-the-secret", "us")
    with pytest.raises(TuyaError, match="no data centre"):
        await watcher.link(family.erin, ACCESS_ID, SECRET, "mars")
    with pytest.raises(TuyaError, match="Access ID"):
        await watcher.link(family.erin, "", SECRET, "us")
    assert not watcher.account.linked()
    assert watcher.devices() == []


async def test_device_lists_come_in_pages(family: SeededFamily, pets: FakeTuya) -> None:
    pets.page_size = 2
    watcher = watcher_for(family, pets)
    added = await watcher.link(family.erin, ACCESS_ID, SECRET, "us")
    assert len(added) == 3


async def test_tokens_are_renewed_and_a_dead_one_is_replaced(
    linked: TuyaWatcher, pets: FakeTuya
) -> None:
    await linked.poll()
    tokens = [c for c in pets.calls if c.startswith("GET /v1.0/token")]
    assert tokens == ["GET /v1.0/token"]  # one token for the lot
    clock.advance(timedelta(hours=2))  # past its two hours: renewed with the refresh token
    await linked.poll()
    assert [c for c in pets.calls if c.startswith("GET /v1.0/token")][-1].startswith(
        "GET /v1.0/token/"
    )
    pets.expire_tokens()  # Tuya forgets it early: a new one, and the call again
    clock.advance(timedelta(minutes=10))
    assert await linked.poll() == 0
    assert family_state(linked, FEEDER) == "plenty of food (64% left)"


def family_state(watcher: TuyaWatcher, external_id: str) -> str | None:
    device = next(d for d in watcher.devices() if d.external_id == external_id)
    return watcher.states().get(device.id)


async def test_the_first_read_is_the_starting_point_then_changes_are_events(
    linked: TuyaWatcher, pets: FakeTuya
) -> None:
    events = heard(linked)
    pets.set_status(FEEDER, "standard_low")
    assert await linked.poll() == 0  # low already when linked: nothing announced
    assert family_state(linked, FEEDER) == "running low on food (15% left)"
    assert family_state(linked, FOUNTAIN) is None  # unmapped: not read
    pets.set_status(FEEDER, "standard_empty")
    pets.set_status(FAULTY, "fault_motor")
    assert await linked.poll() == 2
    assert [(e.kind, e.detail, e.gone) for e in events] == [
        (FOOD, OUT, False),  # worse words for the same problem
        ("jammed", "the food's stuck (motor fault)", False),
    ]
    pets.set_status(FEEDER, "standard_plenty")
    await linked.poll()
    assert (events[-1].kind, events[-1].detail, events[-1].gone) == (FOOD, OUT, True)
    assert await linked.poll() == 0  # nothing changed


async def test_offline_limited_and_a_lapsed_plan(
    family: SeededFamily, linked: TuyaWatcher, pets: FakeTuya
) -> None:
    told: list[str] = []

    async def tell(why: str) -> None:
        told.append(why)

    linked.broken_listeners.append(tell)
    pets.offline(FEEDER)
    await linked.poll()
    assert family_state(linked, FEEDER) == "offline"
    pets.limit(times=1)
    await linked.poll()  # asked to wait: no more calls until it's over
    calls = len(pets.calls)
    with pytest.raises(RateLimited):
        await linked.account.status(FEEDER)
    await linked.poll()
    assert len(pets.calls) == calls
    clock.advance(timedelta(minutes=11))
    pets.lapse()
    await linked.poll()
    await linked.poll()
    assert len(told) == 1 and "extend it on Tuya's site" in told[0]
    assert linked.account.problem() == told[0]
    calls = len(pets.calls)
    assert await linked.poll() == 0  # broken: no calls until it's linked again
    assert len(pets.calls) == calls
    pets.lapsed = False
    await linked.link(family.erin, ACCESS_ID, SECRET, "us")
    assert linked.account.problem() is None


async def test_feedings_are_read_hourly_and_kept_once(
    family: SeededFamily, linked: TuyaWatcher, pets: FakeTuya
) -> None:
    now = clock.now()
    pets.fed(FEEDER, 2, now - timedelta(hours=3))
    pets.fed(FEEDER, 1, now - timedelta(days=3))  # before the first look back
    await linked.poll()
    device = next(d for d in linked.devices() if d.external_id == FEEDER)
    assert linked.last_fed(device) == (now - timedelta(hours=3), 2)
    clock.advance(timedelta(minutes=10))
    pets.fed(FEEDER, 3, clock.now())
    await linked.poll()  # not an hour yet
    assert linked.last_fed(device) == (now - timedelta(hours=3), 2)
    clock.advance(timedelta(minutes=50))
    await linked.poll()
    assert linked.last_fed(device) == (now + timedelta(minutes=10), 3)
    assert family.db.scalar("SELECT COUNT(*) FROM feeder_feeds") == 2


async def test_feeding_logs_come_in_pages(linked: TuyaWatcher, pets: FakeTuya) -> None:
    pets.page_size = 1
    for hours in (5, 4, 3):
        pets.fed(FEEDER, hours, clock.now() - timedelta(hours=hours))
    await linked.poll()
    device = next(d for d in linked.devices() if d.external_id == FEEDER)
    assert linked.last_fed(device) == (clock.now() - timedelta(hours=3), 3)


async def test_read_now_and_the_raw_data_points(linked: TuyaWatcher, pets: FakeTuya) -> None:
    device = next(d for d in linked.devices() if d.external_id == FEEDER)
    pets.set_status(FEEDER, "standard_low")
    reading = await linked.read(device)
    assert reading.problems == {FOOD: LOW}
    raw = linked.raw(device)
    assert raw is not None
    assert (raw["category"], raw["product_id"]) == ("cwwsq", "pqxstdfeeder01")
    assert {"code": "surplus_grain", "value": 15} in raw["status"]
    specs = [c for c in pets.calls if c.endswith("/specifications")]
    await linked.read(device)
    assert [c for c in pets.calls if c.endswith("/specifications")] == specs  # read once


async def test_capture_leaves_out_ids_keys_and_names(linked: TuyaWatcher, pets: FakeTuya) -> None:
    pets.specs[FAULTY]["id"] = FAULTY  # as some answers carry it
    device = next(d for d in linked.devices() if d.external_id == FAULTY)
    pets.set_status(FAULTY, "fault_motor")
    captured = await linked.capture(device)
    text = json.dumps(captured)
    assert FAULTY not in text and "Mochi" not in text and "k3yk3y" not in text
    assert captured["product_id"] == "pqxfaultfeed02"
    assert captured["reading"]["problems"] == {"jammed": "the food's stuck (motor fault)"}
    assert captured["specification"]["status"][2]["code"] == "fault"


async def test_the_capture_command_writes_a_file_per_device(
    linked: TuyaWatcher, tmp_path: Path
) -> None:
    written = await write_captures(linked, tmp_path / "captured")
    assert [p.name for p in written] == [
        "pqxstdfeeder01-1.json",
        "pqxfaultfeed02-2.json",
        "pqxfountain003-3.json",
    ]
    saved = json.loads(written[0].read_text())
    assert saved["reading"]["said"] == "plenty of food (64% left)"


def test_the_capture_command_needs_tuya_linked(
    family: SeededFamily, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import themi.cli as cli

    monkeypatch.setattr(cli, "_store", lambda: family.store)
    assert main(["tuya", "capture"]) == 1
    assert "Link Tuya on the website's Accounts page first." in capsys.readouterr().err
