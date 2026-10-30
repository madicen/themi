import re
from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from themi.connectors.gcal import event_id
from themi.core.calendar import event_body
from themi.core.tasks import Task

# What Google accepts as an event id: base32hex (0-9, a-v), 5 to 1024 characters.
GOOGLE_EVENT_ID = re.compile(r"[a-v0-9]{5,1024}")


@given(source_id=st.integers(min_value=1, max_value=10**12), seed=st.text(max_size=40))
def test_event_ids_are_valid_and_stable(source_id: int, seed: str) -> None:
    eid = event_id("task", source_id, seed)
    assert GOOGLE_EVENT_ID.fullmatch(eid)
    assert eid == event_id("task", source_id, seed)
    assert eid != event_id("task", source_id + 1, seed)


def test_different_families_get_different_ids() -> None:
    assert event_id("task", 7, "2026-10-01T00:00:00+00:00") != event_id(
        "task", 7, "2026-10-02T00:00:00+00:00"
    )


def task(status: str = "open") -> Task:
    return Task(7, "Call the plumber", "call", 2, 2, 1, "", status, date(2026, 12, 31))


def test_an_event_is_an_all_day_reminder() -> None:
    body = event_body(task(), "Husband")
    assert body["summary"] == "Call the plumber"
    assert body["start"] == {"date": "2026-12-31"} and body["end"] == {"date": "2027-01-01"}
    assert body["transparency"] == "transparent"
    assert body["description"] == "For Husband. From Themi's task list."
    assert event_body(task("done"), None)["summary"] == "Done: Call the plumber"


def test_an_event_named_only_as_the_time_to_fit_around_is_an_anchor() -> None:
    """Bug #73: "plenty of time before tutoring" named the tutoring, but not to move it."""
    from themi.core.events import named_as_anchor

    title = "Tutor Gabriel (Illems)"
    said = "Let's move that up to 12pm so that there's plenty of time before tutoring"
    assert named_as_anchor(title, said)
    assert named_as_anchor(title, "Run at 12, well ahead of the tutoring")
    assert not named_as_anchor(title, "Move tutoring to 4pm")
    assert not named_as_anchor(title, "Move tutoring to 4, after lunch")
    assert not named_as_anchor(title, "Move that to 4")  # not named at all: the model decides
