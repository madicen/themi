from datetime import UTC, date, datetime

from themi.channels.pda import find_demands, split_quotes
from themi.core import calls, meals
from themi.core.calls import script_text
from themi.core.meals import pantry_lines
from themi.core.pantry import PantryItem

TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)


def item(name: str, status: str = "plenty", staple: bool = False, expiry: date | None = None):
    return PantryItem(1, name, status, "said", staple, expiry, NOW)  # type: ignore[arg-type]


def test_the_pantry_is_listed_use_soon_first_then_staples_and_never_whats_out() -> None:
    lines = pantry_lines(
        [
            item("rice", staple=True),
            item("cheese"),
            item("eggs", status="out", staple=True),
            item("spinach", expiry=date(2026, 10, 22)),
            item("yogurt", expiry=date(2026, 10, 21)),
            item("pasta", status="low", staple=True),
            item("jam", expiry=date(2027, 1, 1)),
        ],
        TODAY,
    )
    assert lines == [
        "- yogurt (use soon: by today)",
        "- spinach (use soon: by tomorrow)",
        "- pasta (staple, running low)",
        "- rice (staple)",
        "- cheese",
        "- jam (use by 2027-01-01)",
    ]


SCRIPT = {
    "objective": "Get the water heater fixed this week",
    "opening_line": "Hi, this is the Household family calling about our water heater.",
    "questions": ["Can someone come out Thursday?", "What will the visit cost?"],
    "acceptable_outcomes": ["A visit booked by Friday"],
    "fallback": "Ask for the earliest slot and a number to call back.",
    "effort": 2,
}


def test_scripts_are_quoted_so_the_shield_keeps_them() -> None:
    text = script_text("the plumber", SCRIPT)
    own, quotes = split_quotes(text)
    assert own.strip().startswith("A script for the call to the plumber:")
    (quoted,) = quotes
    assert "> - Can someone come out Thursday?" in quoted
    assert '> Opening: "Hi, this is the Household family' in quoted
    assert "> If not: Ask for the earliest slot" in quoted


def test_meal_and_call_texts_pass_the_strictest_pda_check() -> None:
    texts = [
        meals.OFFER_TEXT.format(first="Fried rice (15 min)", second="Toast (5 min)"),
        split_quotes(meals.CHOSEN_TEXT.format(title="Fried rice", steps="Fry it."))[0],
        meals.NO_IDEAS_TEXT,
        calls.OUTCOME_ASK.format(vendor="the plumber"),
        calls.NO_SCRIPT_TEXT,
        split_quotes(script_text("the plumber", SCRIPT))[0],
    ]
    for text in texts:
        assert find_demands(text, 3) == [], text
