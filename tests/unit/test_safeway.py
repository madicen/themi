"""35c: the Safeway cart's checks and messages, without the app."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from themi_home.safeway import (
    InvalidResults,
    Job,
    check_results,
    links_text,
    list_entry,
    result_text,
)

JOB = Job(
    1,
    1,
    None,
    [{"name": "eggs", "qty": 1}, {"name": "oat milk", "qty": 2}, {"name": "bananas", "qty": 1}],
    "claimed",
    datetime(2026, 10, 31, tzinfo=UTC),
)
EGGS = {
    "id": "960304348",
    "name": "Lucerne Farms Eggs Cage Free Large - 18 Count",
    "size": "18 Count",
    "price": 5.99,
}


def line(name: str, status: str = "added", **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "qty": 1, "product": None, **extra}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("eggs", ("eggs", 1)),
        ("2 oat milk", ("oat milk", 2)),
        ("2x oat milk", ("oat milk", 2)),
        ("oat milk x3", ("oat milk", 3)),
        ("oat milk (4)", ("oat milk", 4)),
        ("7up", ("7up", 1)),
        ("1% milk", ("1% milk", 1)),
        ("99 eggs", ("eggs", 20)),
        ("  lots   of   spaces ", ("lots of spaces", 1)),
    ],
)
def test_a_list_name_and_its_quantity(raw: str, expected: tuple[str, int]) -> None:
    assert list_entry(raw) == expected


def test_good_results_are_kept_in_the_jobs_spelling() -> None:
    results = check_results(
        {
            "items": [
                line("Eggs", product=EGGS),
                line("oat milk", "out_of_stock", qty=2),
                line("bananas", "not_found"),
            ],
            "stopped": False,
        },
        JOB,
    )
    assert results["items"][0] == {
        "name": "eggs",
        "status": "added",
        "qty": 1,
        "product": {"id": "960304348", "name": EGGS["name"], "size": "18 Count"},
    }
    assert [r["status"] for r in results["items"]] == ["added", "out_of_stock", "not_found"]
    assert results["stopped"] is False


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"items": "eggs"},
        {"items": [line("eggs")] * 4},  # more than the job has
        {"items": ["eggs"]},
        {"items": [line("caviar")]},  # not in the job
        {"items": [line("eggs"), line("EGGS")]},  # twice
        {"items": [line("x" * 81)]},
        {"items": [line("eggs", "bought")]},
        {"items": [line("eggs", qty=0)]},
        {"items": [line("eggs", qty=21)]},
        {"items": [line("eggs", qty=True)]},
        {"items": [line("eggs", qty="2")]},
        {"items": [line("eggs", product="960304348")]},
        {"items": [line("eggs", product={**EGGS, "id": "96030434a"})]},
        {"items": [line("eggs", product={**EGGS, "id": 960304348})]},
        {"items": [line("eggs", product={**EGGS, "name": ""})]},
        {"items": [line("eggs", product={**EGGS, "name": "x" * 201})]},
        {"items": [line("eggs", product={**EGGS, "size": "x" * 41})]},
        {"items": [line("eggs", product={**EGGS, "price": "free"})]},
        {"items": [line("eggs", product={**EGGS, "price": -1})]},
        {"items": [line("eggs")], "stopped": "Sign in to Safeway"},
    ],
)
def test_bad_results_are_refused(raw: Any) -> None:
    with pytest.raises(InvalidResults):
        check_results(raw, JOB)


def test_the_message_names_the_familys_items() -> None:
    results = check_results(
        {
            "items": [
                line("eggs", product=EGGS),
                line("oat milk", "out_of_stock"),
                line("bananas", product={**EGGS, "id": "1", "name": "Banana"}),
            ]
        },
        JOB,
    )
    assert result_text(results) == (
        "2 things in the Safeway cart; oat milk was out of stock. Ready when you are."
    )


def test_the_message_for_everything_that_went_wrong() -> None:
    job = Job(2, 1, None, [{"name": n, "qty": 1} for n in "abcde"], "claimed", JOB.created_at)
    results = check_results(
        {
            "items": [
                line("a"),
                line("b", "out_of_stock"),
                line("c", "out_of_stock"),
                line("d", "not_found"),
                line("e", "failed"),
            ]
        },
        job,
    )
    assert result_text(results) == (
        "1 thing in the Safeway cart; b and c were out of stock; I couldn't find d; e was not "
        "added. Ready when you are."
    )


def test_the_message_when_the_helper_stopped() -> None:
    results = check_results({"items": [line("eggs", "failed")], "stopped": True}, JOB)
    assert result_text(results) == (
        "Nothing went in the Safeway cart; eggs was not added. The helper stopped partway: "
        "Safeway wants a sign-in in Chrome first."
    )


def test_links_search_for_each_item() -> None:
    assert links_text([{"name": "oat milk", "qty": 2}, {"name": "eggs", "qty": 1}]) == (
        "- oat milk (2): https://www.safeway.com/shop/search-results.html?q=oat%20milk\n"
        "- eggs: https://www.safeway.com/shop/search-results.html?q=eggs"
    )
