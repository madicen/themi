"""WA1: the leave card's states and words (Themi Wall Alerts Plan, "Leaving the house").

A dentist at 3:00 pm, a 35-minute drive: leave by 2:25, getting ready from 2:10.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from themi_google.travel import Leaving
from themi_home.trills import TRILLS, length
from themi_home.wall_alerts import (
    WallAlert,
    countdown,
    drive_words,
    heard,
    kitchen_alerts,
    leave_alert,
    leave_state,
    ranked,
    up_words,
)

LA = ZoneInfo("America/Los_Angeles")


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, 21, hour, minute, second, tzinfo=LA)


def dentist(**changes: object) -> Leaving:
    values: dict[str, object] = dict(
        key="dentist smile dental@2026-10-21T22:00:00Z", member_ids=(1,), names=("Erin",),
        title="Dentist", starts_at=at(15), leave_by=at(14, 25), ready_from=at(14, 10),
        drive_minutes=35, traffic=True,
    )  # fmt: skip
    values.update(changes)
    return Leaving(**values)  # type: ignore[arg-type]


def card(moment: datetime, **changes: object) -> WallAlert:
    found = leave_alert(dentist(**changes), moment, LA, "p0")
    assert found is not None
    return found


@pytest.mark.parametrize(
    ("moment", "state"),
    [
        (at(14, 9, 59), ""),
        (at(14, 10), "ready"),
        (at(14, 19, 59), "ready"),
        (at(14, 20), "almost"),
        (at(14, 24, 59), "almost"),
        (at(14, 25), "go"),
        (at(14, 26, 59), "go"),
        (at(14, 27), "behind"),
        (at(14, 59, 59), "behind"),
        (at(15), ""),
    ],
)
def test_the_states_through_the_afternoon(moment: datetime, state: str) -> None:
    assert leave_state(dentist(), moment) == state


def test_getting_ready_counts_down_to_leave_by_not_the_event() -> None:
    found = card(at(14, 12, 20))
    assert (found.label, found.title, found.numerals, found.counts) == (
        "Time to get ready", "Dentist at 3:00", "12:40", "down",
    )  # fmt: skip
    assert found.sub == "until we leave at 2:25"
    assert found.ends_at == at(14, 25)
    assert (found.bar_from, found.bar_to, found.bar) == ("Ready from 2:10", "Out the door 2:25", 16)
    assert found.detail == "Erin · 35 min drive with traffic"
    assert found.sound == "ready"
    assert [b.label for b in found.buttons] == ["We're off", "Quiet"]


def test_the_last_five_minutes() -> None:
    found = card(at(14, 20, 50))
    assert (found.label, found.numerals, found.sub, found.sound) == (
        "Almost time to go", "4:10", "out the door at 2:25", "five",
    )  # fmt: skip


def test_time_to_go() -> None:
    found = card(at(14, 25))
    assert (found.label, found.numerals, found.counts, found.sound) == (
        "Time to go", "Time to go", "", "go",
    )  # fmt: skip
    assert [b.answer for b in found.buttons] == ["off"]


def test_running_behind_says_when_leaving_now_gets_them_there_and_is_silent() -> None:
    found = card(at(14, 28))
    assert (found.label, found.title, found.numerals) == ("Dentist at 3:00", "Leaving now", "3:03")
    assert found.sub == "gets you there around then, 35 min drive with traffic"
    assert found.sound == "" and found.counts == ""
    assert "late" not in f"{found.label} {found.title} {found.sub}".lower()
    assert [b.answer for b in found.buttons] == ["off", "not_going"]


def test_a_private_event_shows_no_title() -> None:
    found = card(at(14, 12), title="")
    assert found.title == "Leaving at 2:25"
    assert "Dentist" not in f"{found.label} {found.title} {found.sub} {found.detail}"


def test_both_of_them_and_a_rough_guess() -> None:
    found = card(at(14, 12), names=("Erin", "Husband"), member_ids=(1, 2), traffic=False)
    assert found.detail == "Erin and Husband · 35 min drive, a rough guess"


def test_countdown_and_drive_words() -> None:
    assert [countdown(s) for s in (-5, 0, 59, 760, 3900)] == [
        "0:00", "0:00", "0:59", "12:40", "1:05:00",
    ]  # fmt: skip
    assert drive_words(75, True) == "1 hr 15 min drive with traffic"


def test_only_the_soonest_leave_and_at_most_two() -> None:
    first = card(at(14, 12))
    later = leave_alert(
        dentist(key="b", leave_by=at(14, 40), ready_from=at(14, 10)), at(14, 12), LA, "p0"
    )
    assert later is not None
    assert ranked([later, first]) == [first]


# ----- WA3: kitchen timers ---------------------------------------------------------------


def timer(id_: int, ends: datetime, minutes: float = 10, **changes: object) -> dict[str, object]:
    row: dict[str, object] = dict(
        id=id_, session_id=7, member_id=1, recipe="Pad Thai", step="3", label="Sauce, step 3",
        minutes=minutes, ends_at=ends.isoformat(), fired_at=None,
    )  # fmt: skip
    row.update(changes)
    return row


def test_the_soonest_running_timer_and_the_next() -> None:
    rows = [
        timer(1, at(17, 47)),
        timer(2, at(17, 56), 22, step="5", label="Noodles, step 5"),
    ]
    (card,) = kitchen_alerts(rows, at(17, 40, 48), LA, {1: "p0"})  # type: ignore[arg-type]
    assert (card.state, card.label, card.title, card.numerals, card.counts) == (
        "running", "Back to the kitchen in", "Pad Thai · Sauce, step 3", "6:12", "down",
    )  # fmt: skip
    assert (card.bar, card.bar_from, card.bar_to) == (38, "of 10:00", "done at 5:47")
    assert (card.next_line, card.next_at) == ("Then: Pad Thai · Noodles, step 5", at(17, 56))
    assert (card.icon, card.sound, card.buttons, card.rank) == ("pot", "", (), 2)


def test_a_timer_thats_up_counts_up_and_comes_first() -> None:
    rows = [
        timer(1, at(17, 47), fired_at=at(17, 47).isoformat()),
        timer(2, at(17, 56), step="5", label="Noodles, step 5"),
    ]
    up, running = kitchen_alerts(rows, at(17, 47, 42), LA, {})  # type: ignore[arg-type]
    assert (up.state, up.label, up.numerals, up.sub, up.up_for) == (
        "up", "Pad Thai · Sauce, step 3", "Kitchen time", "10 minutes are up", "+0:42",
    )  # fmt: skip
    assert (up.sound, up.rank, [b.answer for b in up.buttons]) == ("kitchen", 0, ["got_it"])
    assert up.next_line == "Next: Pad Thai · Noodles, step 5"
    assert running.title == "Pad Thai · Noodles, step 5"
    leave = card(at(14, 12))
    assert [a.kind for a in ranked([leave, running, up])] == ["kitchen", "leave"]
    assert ranked([leave, running]) == [leave, running]


def test_a_timer_from_chat_shows_a_clock_and_its_own_label() -> None:
    rows = [timer(1, at(17, 47), session_id=None, label="Tea", recipe="Tea")]
    (card,) = kitchen_alerts(rows, at(17, 40), LA, {})  # type: ignore[arg-type]
    assert (card.icon, card.title) == ("clock", "Tea")


@pytest.mark.parametrize(
    ("minutes", "said"),
    [(10, "10 minutes are up"), (1, "1 minute is up"), (0.5, "30 seconds are up"),
     (2.5, "2.5 minutes are up"), (90, "1 hr 30 min is up")],
)  # fmt: skip
def test_up_words(minutes: float, said: str) -> None:
    assert up_words(minutes) == said


# ----- WA4: Themi's trills ---------------------------------------------------------------

TRILL_DIR = Path(__file__).parents[2] / "src/themi_home/web/static/audio/trills"
SCRIPT = (Path(__file__).parents[2] / "src/themi_home/web/static/wall.js").read_text()


@pytest.mark.parametrize(
    ("sounds", "leave", "kitchen"),
    [("On", "ready", "kitchen"), ("Kitchen only", "", "kitchen"), ("Off", "", "")],
)
def test_which_sounds_play_by_the_setting(sounds: str, leave: str, kitchen: str) -> None:
    up = kitchen_alerts(
        [timer(1, at(17, 47), fired_at=at(17, 47).isoformat())], at(17, 48), LA, {}  # type: ignore[list-item]
    )[0]
    assert heard(card(at(14, 12)), sounds).sound == leave
    assert heard(up, sounds).sound == kitchen
    assert heard(up, sounds).chirp == bool(kitchen)
    assert heard(replace(up, silent=True), "On").sound == ""  # Quiet


def test_a_timer_thats_up_trills_once_more_after_two_minutes() -> None:
    row = timer(1, at(17, 47), fired_at=at(17, 47).isoformat())
    first = kitchen_alerts([row], at(17, 48, 59), LA, {})[0]  # type: ignore[list-item]
    again = kitchen_alerts([row], at(17, 49), LA, {})[0]  # type: ignore[list-item]
    assert (first.sound_key, again.sound_key) == ("up", "up-again")
    assert first.sound == again.sound == "kitchen"


def test_every_trill_is_made_and_short() -> None:
    assert set(TRILLS) == {"ready", "five", "go", "kitchen", "got-it"}
    for name in TRILLS:
        assert (TRILL_DIR / f"{name}.m4a").stat().st_size > 1000, name
        assert length(name) < 1.5, name


def test_the_page_plays_each_once_and_waits_for_a_touch() -> None:
    assert 'sessionStorage.getItem(key)' in SCRIPT
    assert '"wall-trill:" + card.getAttribute("data-alert") + ":" + card.getAttribute("data-sound-key")' in SCRIPT
    assert "if (chip) chip.hidden = false;  // not allowed yet" in SCRIPT
    assert 'sound.volume = list ? Number(list.getAttribute("data-volume"))' in SCRIPT
