"""D5a: the fakes save as JSON and come back the same, so `make dev` keeps them."""

from __future__ import annotations

import itertools
import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.gtasks_api import FakeGtasks
from tests.fakes.home_connect import FakeHomeConnect
from tests.fakes.keep import FakeItem, FakeKeep
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fakes.roborock import FakeRoborock
from tests.fakes.snapshot import SnapshotError, Snapshots, dump, load
from tests.fakes.thinq import FakeThinq
from tests.fakes.travel import FakeTravel
from themi import clock

ERIN = "erin@gmail.com"


def through_json(value: Any) -> Any:
    return load(json.loads(json.dumps(dump(value))))


def test_what_plain_json_cant_hold_comes_back() -> None:
    value = {
        "pair": ("a", 1),
        "seen": {1, 2},
        "calls": Counter({"add": 2}),
        "at": datetime(2026, 11, 3, 9, 30, tzinfo=UTC),
        "day": date(2026, 11, 3),
        "by_id": {101: "Family"},
        "by_pair": {("uid", "m-erin", "2026-11-03"): "done"},
        "~sneaky": "a key that looks like a tag",
        "item": FakeItem("item-1", "milk", checked=True),
        "nested": [[{"x": (1, 2)}]],
    }
    assert through_json(value) == value


def test_a_counter_keeps_its_place_and_isnt_used_up() -> None:
    ids = itertools.count(7)
    saved = dump(ids)
    assert next(ids) == 7  # reading it didn't take 7
    assert next(load(saved)) == 7


def test_only_the_fakes_and_connectors_dataclasses_are_built() -> None:
    for name in ("themi.accounts.models:Member", "os:path", "subprocess:Popen"):
        with pytest.raises(SnapshotError, match="won't build"):
            load({"~dataclass": name, "fields": {}})
    with pytest.raises(SnapshotError, match="isn't a dataclass"):
        load({"~dataclass": "tests.fakes.keep:FakeKeep", "fields": {}})


def test_what_cant_be_saved_says_so() -> None:
    with pytest.raises(SnapshotError, match="can't save a function"):
        dump(lambda: None)


# ----- each fake -------------------------------------------------------------------------


def google() -> FakeGoogle:
    fake = FakeGoogle()
    fake.add_account(ERIN)
    fake._issue_access(ERIN)
    return fake


def gmail() -> FakeGmail:
    fake = FakeGmail(FakeGoogle())
    gid = fake.deliver(ERIN, sender="Bank <a@bank.example>", subject="Statement", text="Hi")
    fake.by_hand(ERIN, gid, remove=["UNREAD"])
    return fake


def gcal() -> FakeGcal:
    fake = FakeGcal(FakeGoogle())
    fake.add_calendar(ERIN, "Themi")
    fake.add_event(
        ERIN, "2026-10-27T15:00:00-07:00", "2026-10-27T16:00:00-07:00", summary="Dentist"
    )
    return fake


def gtasks() -> FakeGtasks:
    fake = FakeGtasks(FakeGoogle())
    fake.add(ERIN, "Buy milk")
    return fake


def cozyla() -> FakeCozyla:
    fake = FakeCozyla()
    erin = fake.add_member("Erin")
    family = fake.add_list("Family")
    fake.tick(fake.add_todo(family, "Call the vet"))
    uid = fake.add_chore("Bins", [erin], every="Weekly", days="Tuesday")
    fake.tick_chore(uid, erin, date(2026, 10, 27))
    fake.tick_routine(fake.add_routine(erin, "Walk dog", "Morning"), date(2026, 10, 27))
    fake.tokens.add("token-1")
    return fake


def home_connect() -> FakeHomeConnect:
    fake = FakeHomeConnect()
    fake.add_appliance("BOSCH-SMV-1", "Dishwasher")
    fake.set_state("BOSCH-SMV-1", "Run", seconds_left=2700)
    fake.access["token"] = datetime(2026, 11, 4, tzinfo=UTC)
    fake.refresh_tokens.add("refresh")
    return fake


def thinq() -> FakeThinq:
    fake = FakeThinq()
    fake.add_device("lg-washer-1", "DEVICE_WASHER", "Washer")
    fake.set_run_state("lg-washer-1", "RUNNING")
    fake.clients.add("client-1")
    return fake


def roborock() -> FakeRoborock:
    fake = FakeRoborock()
    fake.add_robot("rr-duid-1", "Robbie")
    fake.set_status("rr-duid-1", "trapped")
    fake.rooms["rr-duid-1"] = "Kitchen"
    return fake


def keep() -> FakeKeep:
    fake = FakeKeep()
    fake.check(ERIN, fake.put(ERIN, "milk"))
    return fake


def ourgroceries() -> FakeOurGroceries:
    clock.freeze(datetime(2026, 11, 3, 17, tzinfo=UTC))
    fake = FakeOurGroceries()
    fake.cross(fake.put("eggs"))
    return fake


def travel() -> FakeTravel:
    fake = FakeTravel()
    fake.place("12 Main St", 37.70, -122.40)
    fake.minutes = 35
    return fake


FAKES: dict[str, Callable[[], Snapshots]] = {
    "google": google,
    "gmail": gmail,
    "gcal": gcal,
    "gtasks": gtasks,
    "cozyla": cozyla,
    "home_connect": home_connect,
    "thinq": thinq,
    "roborock": roborock,
    "keep": keep,
    "ourgroceries": ourgroceries,
    "travel": travel,
}


# The Google APIs' fakes are made over a fake Google.
EMPTY: dict[str, Callable[[], Snapshots]] = {
    "gmail": lambda: FakeGmail(FakeGoogle()),
    "gcal": lambda: FakeGcal(FakeGoogle()),
    "gtasks": lambda: FakeGtasks(FakeGoogle()),
}


@pytest.mark.parametrize("name", FAKES)
def test_each_fake_comes_back_as_it_was(name: str) -> None:
    filled = FAKES[name]()
    saved = json.loads(json.dumps(filled.snapshot()))
    fresh = EMPTY.get(name, lambda: type(filled)())()
    assert fresh.snapshot() != filled.snapshot()  # the fill shows
    fresh.restore(saved)
    assert fresh.snapshot() == filled.snapshot()


def test_a_restored_fake_carries_on_numbering() -> None:
    first = keep()
    second = FakeKeep()
    second.restore(json.loads(json.dumps(first.snapshot())))
    assert first.put(ERIN, "bread") == second.put(ERIN, "bread")  # the same next id


def test_what_isnt_state_starts_empty() -> None:
    fake = keep()
    fake.fail("apply")
    again = FakeKeep()
    again.restore(fake.snapshot())
    assert not again._failures and not again.calls
