"""F49i: where an entry is in a recipe doc, to delete it when it moves into the cookbook:
its Heading 4 through its `-----` (or a rule), or up to the next heading, or the doc's end."""

from __future__ import annotations

from typing import Any

from tests.fixtures.cookbook import document, recipe
from themi_home.cookbook import delete_requests, entry_range, parse

TOAST = recipe("Toast", ["1 slice bread"], ["Toast it."])
JAM = recipe("Jam", ["1 cup berries"], ["Cook it down."])


def texts_between(doc: dict[str, Any], at: tuple[int, int]) -> list[str]:
    return [
        e["paragraph"]["elements"][-1]["textRun"]["content"].rstrip("\n")
        for e in doc["body"]["content"]
        if at[0] <= e["startIndex"] < at[1]
    ]


def key_of(doc: dict[str, Any], name: str) -> str:
    return next(r.key for r in parse(doc).recipes if r.name == name)


def test_through_its_separator() -> None:
    doc = document([("T", "Recipes to try"), *TOAST, *JAM])
    at = entry_range(doc, key_of(doc, "Toast"))
    assert at is not None
    assert texts_between(doc, at) == [
        "Toast", "Ingredients", "1 slice bread", "Instructions", "Toast it.", "-----",
    ]  # fmt: skip


def test_the_last_entry_runs_to_the_docs_end() -> None:
    doc = document([("T", "Recipes to try"), *TOAST, *JAM])
    at = entry_range(doc, key_of(doc, "Jam"))
    assert at is not None
    assert texts_between(doc, at)[0] == "Jam"
    assert at[1] == doc["body"]["content"][-1]["endIndex"] - 1  # the body's last newline stays


def test_a_rule_ends_it_too() -> None:
    doc = document([("T", "Recipes to try"), *TOAST[:-1], ("HR",), *JAM])
    at = entry_range(doc, key_of(doc, "Toast"))
    assert at is not None
    assert texts_between(doc, at)[-1] == ""  # the rule's paragraph
    assert "Jam" not in texts_between(doc, at)


def test_without_a_separator_it_stops_at_the_next_heading() -> None:
    doc = document([("T", "Recipes to try"), *TOAST[:-1], *JAM])
    at = entry_range(doc, key_of(doc, "Toast"))
    assert at is not None
    assert texts_between(doc, at)[-1] == "Toast it."


def test_one_not_there() -> None:
    doc = document([("T", "Recipes to try"), *TOAST])
    assert entry_range(doc, "h.nope") is None


def test_the_request() -> None:
    assert delete_requests((5, 40)) == [
        {"deleteContentRange": {"range": {"startIndex": 5, "endIndex": 40}}}
    ]
