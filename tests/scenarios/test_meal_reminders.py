"""35a: meal reminders and takeout rescue. The clock starts Wednesday 21 October 2026, 9 am
in Los Angeles; Erin's quiet hours are 21:30 to 08:00, her husband's 23:00 to 07:00. The
family's takeout budget is $200 a month."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from tests.fixtures.web import csrf_of, sign_in, web_client
from tests.scenarios.harness import Scenario
from tests.scenarios.test_meals_calls import MEALS
from themi import clock
from themi.ai.errors import PermanentError
from themi.core import keys
from themi_home.meals import Meals
from themi_home.spending import Spending
from themi_home.takeout import Takeout


def meals(scenario: Scenario) -> Meals:
    assert scenario.app.services.maybe(keys.meals) is not None
    return scenario.app.services.get(keys.meals)


def takeout(scenario: Scenario) -> Takeout:
    assert scenario.app.services.maybe(keys.takeout) is not None
    return scenario.app.services.get(keys.takeout)


def spending(scenario: Scenario) -> Spending:
    assert scenario.app.services.maybe(keys.spending) is not None
    return scenario.app.services.get(keys.spending)


async def say(scenario: Scenario, name: str, said: str, tool: str, args: dict[str, Any]) -> None:
    scenario.primary.queue_tool_call(tool, args)
    scenario.primary.queue_text("Okay.")
    await scenario.say(name, said)


async def nudges(scenario: Scenario) -> object:
    sent = await scenario.run_periodic("meals.nudges")
    await scenario.advance()
    return sent


def reminders(scenario: Scenario, name: str) -> list[str]:
    return [t for t in scenario.inbox(name) if t.startswith("It's been a while")]


# ----- meal reminders -------------------------------------------------------------------


async def test_a_meal_said_in_chat_is_logged(scenario: Scenario) -> None:
    await say(scenario, "Erin", "just had breakfast", "log_meal", {"what": "breakfast",
              "minutes_ago": 30})  # fmt: skip
    assert meals(scenario).last_meal(scenario.member("Erin")) == clock.now() - timedelta(minutes=30)
    row = scenario.app.db.one("SELECT what, source FROM meals_eaten")
    assert row is not None and (row["what"], row["source"]) == ("breakfast", "chat")


async def test_one_reminder_per_gap_with_two_ideas(scenario: Scenario) -> None:
    await say(scenario, "Erin", "just had breakfast", "log_meal", {"what": "", "minutes_ago": 0})
    clock.advance(timedelta(hours=4, minutes=45))  # the default gap is 5 hours
    assert await nudges(scenario) == 0

    clock.advance(timedelta(minutes=15))
    scenario.primary.queue_structured(MEALS)
    assert await nudges(scenario) == 1
    (reminder,) = reminders(scenario, "Erin")
    assert reminder.splitlines()[1] == "Two easy options, if either appeals:"
    assert scenario.last_buttons("Erin") == ["Spinach egg fried rice", "Cheese toast and soup"]
    assert not reminders(scenario, "Husband")  # he hasn't logged a meal: never reminded

    clock.advance(timedelta(minutes=30))
    assert await nudges(scenario) == 0  # one per gap

    await scenario.tap("Erin", "Cheese toast and soup")  # what they picked counts as a meal
    row = scenario.app.db.one("SELECT what, source FROM meals_eaten ORDER BY id DESC")
    assert row is not None and (row["what"], row["source"]) == ("Cheese toast and soup",
                                                               "suggestion")  # fmt: skip
    clock.advance(timedelta(hours=5))
    scenario.primary.queue_structured(MEALS)
    assert await nudges(scenario) == 1  # a new meal, a new gap
    assert len(reminders(scenario, "Erin")) == 2


async def test_no_reminder_in_quiet_hours_and_the_gap_starts_again_in_the_morning(
    scenario: Scenario,
) -> None:
    clock.advance(timedelta(hours=11))  # 20:00
    meals(scenario).log_eaten(scenario.member("Erin"), "dinner", source="device")
    clock.advance(timedelta(hours=5))  # 01:00, past the gap but quiet
    assert await nudges(scenario) == 0
    clock.advance(timedelta(hours=7, minutes=30))  # 08:30, half an hour after quiet hours
    assert await nudges(scenario) == 0
    clock.advance(timedelta(hours=4, minutes=30))  # 13:00, five hours after they ended
    scenario.primary.queue_structured(MEALS)
    assert await nudges(scenario) == 1


async def test_without_meal_ideas_the_reminder_still_goes_and_lapses_if_held(
    scenario: Scenario,
) -> None:
    meals(scenario).log_eaten(scenario.member("Erin"))
    clock.advance(timedelta(hours=5))
    scenario.primary.queue_error(PermanentError("no key"), op="structured")
    scenario.fallback.queue_error(PermanentError("no key"), op="structured")
    assert await nudges(scenario) == 1
    assert reminders(scenario, "Erin") == [
        "It's been a while since you last ate, as far as I know. A bite might help, whenever suits."
    ]


async def test_someone_who_stopped_logging_is_not_reminded(scenario: Scenario) -> None:
    meals(scenario).log_eaten(scenario.member("Erin"))
    clock.advance(timedelta(days=2, hours=1))
    assert await nudges(scenario) == 0


async def test_a_paused_reminder_lapses_rather_than_arriving_late(scenario: Scenario) -> None:
    await say(scenario, "Erin", "no meal reminders today", "pause_messages",
              {"topic": "meals", "duration": "today"})  # fmt: skip
    meals(scenario).log_eaten(scenario.member("Erin"))
    clock.advance(timedelta(hours=5))
    scenario.primary.queue_structured(MEALS)
    assert await nudges(scenario) == 1
    assert not reminders(scenario, "Erin")
    clock.advance(timedelta(hours=18))  # the pause is over; the reminder has lapsed
    await scenario.advance()
    assert not reminders(scenario, "Erin")


# ----- takeout rescue -------------------------------------------------------------------


def favourite(scenario: Scenario, name: str = "Thai Place", cents: int = 34_00) -> int:
    saved = takeout(scenario).save_favourite(
        scenario.member("Erin"),
        name,
        "https://www.doordash.com/store/thai-place-123",
        ["Pad thai", "Spring rolls"],
        cents,
    )
    return saved.id


def both_low(scenario: Scenario) -> None:
    for name in ("Erin", "Husband"):
        scenario.app.services.energy.record(scenario.member(name), "day_level", -1, "low day")


def at_dinner(scenario: Scenario) -> None:
    clock.advance(timedelta(hours=9))  # 18:00


async def rescue(scenario: Scenario) -> object:
    staged = await scenario.run_periodic("takeout.rescue")
    await scenario.advance()
    return staged


def staged(scenario: Scenario) -> list[dict[str, Any]]:
    return scenario.app.db.query(
        "SELECT * FROM pending_actions WHERE category = 'doordash_order' ORDER BY id"
    )


async def test_takeout_is_staged_when_everyone_is_low_and_nobody_has_eaten(
    scenario: Scenario,
) -> None:
    favourite(scenario)
    both_low(scenario)
    at_dinner(scenario)
    assert takeout(scenario).why_not(clock.now()) is None
    assert await rescue(scenario) is True
    (action,) = staged(scenario)
    assert action["status"] == "pending"
    assert action["summary"] == (
        "Dinner sorted? Thai Place on DoorDash, about $34.00, $166.00 left of this month's "
        "takeout budget after. If that suits, I'll send the store link and what to order; "
        "the checkout is yours."
    )
    who = scenario.app.store.get_member(action["member_id"]).name
    card = [t for t in scenario.inbox(who) if t.startswith("Dinner sorted?")]
    assert card and "%" not in card[0]  # money words only, never an energy score

    await scenario.tap(who, "Go ahead")
    done = scenario.edits(who)[-1]["text"]  # the PDA shield may soften the last line
    assert (
        "Done. Thai Place on DoorDash: https://www.doordash.com/store/thai-place-123\n"
        "- Pad thai\n- Spring rolls\n"
    ) in done
    assert done.endswith("check out there.")
    assert await rescue(scenario) is False  # one a day
    assert takeout(scenario).why_not(clock.now()) == "already staged today"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("lunchtime", "outside the dinner window"),
        ("late", "outside the dinner window"),
        ("one_not_low", "not everyone is low"),
        ("ate", "someone ate recently"),
        ("ordered", "takeout or eating out already today"),
    ],
)
async def test_each_precondition_holds_it_back(
    scenario: Scenario, change: str, reason: str
) -> None:
    favourite(scenario)
    both_low(scenario)
    if change == "lunchtime":
        clock.advance(timedelta(hours=3))  # 12:00
    else:
        at_dinner(scenario)
    if change == "late":
        clock.advance(timedelta(hours=1, minutes=30))  # 19:30, the window has closed
    elif change == "one_not_low":
        scenario.app.services.energy.record(scenario.member("Husband"), "day_level", 1, "great")
    elif change == "ate":
        meals(scenario).log_eaten(scenario.member("Husband"), at=clock.now() - timedelta(hours=2))
    elif change == "ordered":
        spending(scenario).log(scenario.member("Erin"), 25_00, "Pizza", "takeout")
    assert takeout(scenario).why_not(clock.now()) == reason
    assert await rescue(scenario) is False
    assert not staged(scenario)


async def test_a_meal_over_three_hours_ago_does_not_hold_it_back(scenario: Scenario) -> None:
    favourite(scenario)
    both_low(scenario)
    at_dinner(scenario)
    meals(scenario).log_eaten(scenario.member("Husband"), at=clock.now() - timedelta(hours=4))
    assert await rescue(scenario) is True


async def test_tracking_switched_off_is_no_read_so_no_rescue(scenario: Scenario) -> None:
    favourite(scenario)
    both_low(scenario)
    at_dinner(scenario)
    husband = scenario.member("Husband")
    scenario.app.store.update_settings(
        husband, husband.id, tracking={"text_notes": False, "message_timing": False,
                                       "device_activity": False}
    )  # fmt: skip
    assert takeout(scenario).why_not(clock.now()) == "not everyone is low"


async def test_the_budget_and_the_cap_decide_which_favourite(scenario: Scenario) -> None:
    pricey = favourite(scenario, "Sushi Bar", 70_00)  # over the $60 cap
    thai = favourite(scenario, "Thai Place", 34_00)
    pizza = favourite(scenario, "Pizza", 22_00)
    both_low(scenario)
    at_dinner(scenario)
    today = takeout(scenario).today()
    assert takeout(scenario).affordable(today) is not None
    assert takeout(scenario).affordable(today).id == pizza  # type: ignore[union-attr]

    spending(scenario).log(
        scenario.member("Erin"), 170_00, "Catering", "takeout", on=today - timedelta(days=1)
    )  # $30 left: only the pizza fits
    assert takeout(scenario).affordable(today).id == pizza  # type: ignore[union-attr]
    spending(scenario).log(
        scenario.member("Erin"), 10_00, "Coffee", "takeout", on=today - timedelta(days=1)
    )  # $20 left: nothing fits
    assert takeout(scenario).affordable(today) is None
    assert await rescue(scenario) is False
    assert not staged(scenario)
    assert {pricey, thai, pizza}


async def test_a_spent_budget_stages_nothing(scenario: Scenario) -> None:
    favourite(scenario, "Pizza", 22_00)
    both_low(scenario)
    at_dinner(scenario)
    spending(scenario).log(
        scenario.member("Erin"), 230_00, "Party", "takeout",
        on=takeout(scenario).today() - timedelta(days=2),
    )  # fmt: skip
    assert takeout(scenario).budget_left(takeout(scenario).today()) == -30_00
    assert await rescue(scenario) is False


async def test_the_favourite_offered_longest_ago_comes_next(scenario: Scenario) -> None:
    thai = favourite(scenario, "Thai Place", 34_00)
    pizza = favourite(scenario, "Pizza", 22_00)
    both_low(scenario)
    at_dinner(scenario)
    assert await rescue(scenario) is True
    first = scenario.app.db.scalar("SELECT favourite_id FROM takeout_rescues")
    assert first == pizza
    clock.advance(timedelta(days=1))
    both_low(scenario)
    assert await rescue(scenario) is True
    second = scenario.app.db.scalar("SELECT favourite_id FROM takeout_rescues ORDER BY id DESC")
    assert second == thai


async def test_the_card_lapses_after_dinner(scenario: Scenario) -> None:
    favourite(scenario)
    both_low(scenario)
    at_dinner(scenario)
    assert await rescue(scenario) is True
    (action,) = staged(scenario)
    assert action["expires_at"] is not None
    assert action["expires_at"] > clock.now().isoformat()


# ----- the website ----------------------------------------------------------------------


async def test_favourites_are_kept_on_the_website(scenario: Scenario) -> None:
    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Husband")
        page = await site.get("/takeout")
        assert page.status_code == 200 and "No favourites saved yet." in page.text
        assert "When it's offered" not in page.text  # admins only
        csrf = csrf_of(page.text)
        added = await site.post(
            "/takeout",
            data={
                "csrf": csrf,
                "name": "Thai Place",
                "store_url": "https://www.doordash.com/store/thai-place-123",
                "items": "Pad thai\nSpring rolls",
                "amount": "34.50",
            },
        )
        assert added.status_code == 303
        (saved,) = takeout(scenario).favourites()
        assert (saved.items, saved.cents) == (("Pad thai", "Spring rolls"), 34_50)
        page = await site.get("/takeout")
        assert "Thai Place" in page.text and "$34.50" in page.text

        bad = await site.post(
            "/takeout",
            data={"csrf": csrf, "name": "X", "store_url": "javascript:alert(1)", "amount": "5"},
        )
        assert bad.status_code == 303 and len(takeout(scenario).favourites()) == 1

        await site.post(
            f"/takeout/{saved.id}",
            data={"csrf": csrf, "name": "Thai Place", "store_url": saved.store_url,
                  "items": "Pad see ew", "amount": "30"},
        )  # fmt: skip
        assert takeout(scenario).favourites()[0].items == ("Pad see ew",)
        refused = await site.post(f"/takeout/{saved.id}/remove", data={"csrf": "wrong"})
        assert refused.status_code == 403 and takeout(scenario).favourites()
        await site.post(f"/takeout/{saved.id}/remove", data={"csrf": csrf})
        assert takeout(scenario).favourites() == []

        settings = await site.post(
            "/takeout/settings",
            data={"csrf": csrf, "dinner_from": "17:30", "dinner_until": "20:00", "cap": "50"},
        )
        assert settings.status_code == 403  # an admin's to change

    async with web_client(scenario) as site:
        await sign_in(scenario, site, "Erin")
        page = await site.get("/takeout")
        assert "When it's offered" in page.text
        await site.post(
            "/takeout/settings",
            data={"csrf": csrf_of(page.text), "dinner_from": "17:30", "dinner_until": "20:00",
                  "cap": "50"},
        )  # fmt: skip
        settings_now = takeout(scenario).settings()
        assert (settings_now.dinner_from, settings_now.order_cap_cents) == ("17:30", 50_00)
        assert "/takeout" in (await site.get("/spending")).text
