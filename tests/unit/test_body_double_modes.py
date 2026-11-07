"""BD2: the kind of job, the starting table and what's learned from sessions."""

from __future__ import annotations

from themi.core.body_double import GUIDED, SILENT, SPRINT
from themi.core.body_double_modes import (
    ADMIN,
    CHORES,
    DEEP_WORK,
    OFFER_BUTTONS,
    OFFER_TEXT,
    OTHER,
    TABLE,
    TIDY,
    Seen,
    by_words,
    choose,
    learned,
    observations,
    part_of_day,
    rate,
    settled,
)  # fmt: skip


def test_the_words_settle_most_jobs() -> None:
    assert settled("Write the newsletter") == DEEP_WORK
    assert settled("Do the taxes") == ADMIN
    assert settled("Pay the water bill") == ADMIN
    assert settled("Unload the dishwasher") == CHORES
    assert settled("Declutter the garage") == TIDY
    assert settled("Clean up the kitchen") == TIDY  # tidying's words over "clean"
    assert settled("Walk the dog") is None  # nothing: the model is asked
    assert settled("Email the report") is None  # admin and deep work: asked
    assert by_words("Email the report") == (ADMIN, DEEP_WORK)


def test_the_starting_table() -> None:
    assert TABLE == {DEEP_WORK: SILENT, ADMIN: GUIDED, CHORES: GUIDED, TIDY: SPRINT,
                     OTHER: SILENT}  # fmt: skip
    assert choose([], CHORES, "evening") == GUIDED


def test_parts_of_the_day() -> None:
    assert part_of_day(2 * 24 + 9) == "morning"
    assert part_of_day(13) == "afternoon"
    assert part_of_day(5 * 24 + 19) == "evening"
    assert part_of_day(2) == "evening"


def test_the_smoothing() -> None:
    assert rate([]) == 0.5
    assert rate([True]) == 0.75
    assert round(rate([True, True, True]), 3) == 0.875
    assert rate([False]) == 0.25


def seen(mode: str, finished: bool, *, low: bool = False, n: int = 1) -> list[Seen]:
    return [Seen(CHORES, "evening", mode, low, finished)] * n


def test_three_good_sessions_and_a_clear_lead_beat_the_table() -> None:
    assert choose(seen(SPRINT, True, n=2), CHORES, "evening") == GUIDED  # not yet three
    assert choose(seen(SPRINT, True, n=3), CHORES, "evening") == SPRINT
    assert choose(seen(SPRINT, True, n=3), CHORES, "morning") == GUIDED  # another part of day
    close = seen(SPRINT, True, n=3) + seen(GUIDED, True, n=3)
    assert choose(close, CHORES, "evening") == GUIDED  # no clear lead: the table stays


def test_the_energy_split_once_it_has_enough() -> None:
    history = seen(SPRINT, True, n=3) + seen(SPRINT, False, low=True, n=3)
    assert learned(history, CHORES, "evening", low=True)[SPRINT][0] == 3
    assert choose(history, CHORES, "evening", low=False) == SPRINT
    assert choose(history, CHORES, "evening", low=True) == GUIDED
    few = seen(SPRINT, True, n=3) + seen(SPRINT, False, low=True, n=1)
    assert learned(few, CHORES, "evening", low=True)[SPRINT][0] == 4  # too few: whole cell


def row(n: int, mode: str, outcome: str, **more: object) -> dict:
    base = {"id": n, "mode": mode, "outcome": outcome, "category": CHORES, "hour_of_week": 19}
    return {**base, "energy_level": "medium", "switched_from": None, **more}


def test_a_switch_counts_against_the_first_and_for_the_second() -> None:
    rows = [row(1, GUIDED, "switched"), row(2, SPRINT, "stopped", switched_from=1,
                                             category=None)]  # fmt: skip
    assert observations(rows) == [
        Seen(CHORES, "evening", GUIDED, False, False),
        Seen(CHORES, "evening", SPRINT, False, True),
        Seen(CHORES, "evening", SPRINT, False, False),  # its own outcome too
    ]
    assert observations([row(3, SILENT, None)]) == []  # still going: not counted  # type: ignore[arg-type]


ENERGY = ("energy", "tired", "score", "capacity", "usually", "last time", "fail", "percent")


def test_the_offer_never_gives_a_reason() -> None:
    for text in [*OFFER_TEXT.values(), *OFFER_BUTTONS.values()]:
        assert not any(word in text.lower() for word in ENERGY), text
