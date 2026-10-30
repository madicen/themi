"""M1: how a journal entry reads to the model, and what's kept from the model's lists."""

from __future__ import annotations

from datetime import date

from themi.core.journal import Entry, _clean


def test_an_entry_in_one_line() -> None:
    entry = Entry(1, 1, date(2026, 10, 21), ("pacifiers", "the plumber"), ("Basket by the door",))
    assert entry.words() == (
        "Wed 21 Oct 2026: talked about pacifiers; the plumber. Decided: Basket by the door."
    )
    quiet = Entry(2, 1, date(2026, 10, 22), ("a recipe",), ())
    assert quiet.words() == "Thu 22 Oct 2026: talked about a recipe."


def test_the_models_lists_are_tidied_and_capped() -> None:
    assert _clean(["  a  topic ", "", "x" * 300, None], 8) == ["a topic", "x" * 200]
    assert _clean([str(n) for n in range(20)], 8) == [str(n) for n in range(8)]
    assert _clean(None, 8) == []
