"""SP5: what a switch on the Modules page would do, before it's made."""

from __future__ import annotations

from themi.config import available_modules, load_template, parse_config
from themi.modules.planning import Planner
from themi.modules.store import Draft


def planner(config: dict | None = None, draft: Draft | None = None) -> Planner:
    return Planner(
        parse_config(config or {}),
        available_modules(),
        lambda name: load_template(name).modules,
        draft or Draft(),
    )


def test_turning_on_brings_what_it_needs() -> None:
    empty = planner({"template": "empty"})
    assert empty.turn_on("email_triage").on == ("google", "gmail", "email_triage")
    family = planner()
    assert family.turn_on("email_triage").on == ()  # the family has it all already


def test_turning_off_takes_what_needs_it() -> None:
    change = planner().turn_off("google")
    assert change.off[0] == "google"
    assert {"gmail", "email_triage", "noise_digest", "calendar", "task_blocks"} <= set(change.off)
    assert "tasks" not in change.off


def test_a_switch_and_its_undoing_leave_no_change() -> None:
    p = planner({"template": "empty"})
    p.apply(p.turn_on("travel"))
    assert p.draft.modules == {"travel": True}
    assert "travel" in p.desired()
    p.apply(p.turn_off("travel"))
    assert p.draft.modules == {} and "travel" not in p.desired()


def test_the_draft_becomes_a_config() -> None:
    p = planner({"modules": ["-safeway"], "module": {"web_search": {"backend": "tavily"}}})
    p.apply(p.turn_on("safeway"))
    p.apply(p.turn_off("spending"))
    p.draft.sections["web_search"] = {"backend": ""}  # back to the default
    p.draft.sections["travel"] = {}
    config = p.as_config()
    # 35a: takeout needs spending, so it goes with it (EX4a: and expense_sync)
    assert config.removed == ("spending", "expense_sync", "takeout") and config.added == ()
    assert "web_search" not in config.sections


def test_a_template_switch_lists_what_goes_and_what_goes_with_it() -> None:
    switch = planner().switch_template("work")
    gone = dict(switch.off)
    assert "recipes" in gone and "cooking" in gone["recipes"]
    every = {n for name, more in switch.off for n in (name, *more)}
    family = set(load_template("family").modules)
    work = set(load_template("work").modules)
    assert every == family - work
    p = planner()
    p.use_template("work")
    assert p.template == "work" and set(p.desired()) == work
    assert p.as_config().template == "work"


# ----- MP2: many at once ------------------------------------------------------------------


def test_turning_on_many_brings_what_they_need_once_and_says_why() -> None:
    p = planner({"template": "empty"})
    change = p.turn_on_many(["cooking", "cooking_timers", "recipes"])
    assert change.on == ("recipes", "recipe_groceries", "cooking", "cooking_timers")
    why = dict(change.why)
    assert why["recipe_groceries"] == "needed by cooking"
    assert why["recipes"] == "asked"  # asked for too, so it's asked
    assert why["cooking"] == why["cooking_timers"] == "asked"


def test_what_came_on_for_a_module_is_offered_when_it_goes() -> None:
    p = planner({"template": "empty"})
    p.apply(p.turn_on_many(["cooking"]))
    change = p.turn_off_many(["cooking"])
    assert change.off == ("cooking",)
    assert set(change.spare) == {"recipes", "recipe_groceries"}


def test_no_longer_needed_leaves_what_something_staying_needs() -> None:
    p = planner({"template": "empty"})
    p.apply(p.turn_on_many(["cooking"]))
    p.apply(p.turn_on_many(["web_recipes"]))  # needs recipes too
    change = p.turn_off_many(["cooking"])
    assert change.spare == ("recipe_groceries",)
    # and something asked for is never offered
    p.apply(p.turn_on_many(["recipe_groceries"]))
    assert p.turn_off_many(["cooking"]).spare == ()


def test_reasons_kept_past_a_restart_count_too() -> None:
    p = planner({"template": "empty", "modules": ["+recipes", "+recipe_groceries", "+cooking"]})
    p.reasons = {"recipes": "needed by cooking", "recipe_groceries": "needed by cooking"}
    assert set(p.turn_off_many(["cooking"]).spare) == {"recipes", "recipe_groceries"}


def test_asking_for_a_module_already_on_makes_it_asked() -> None:
    p = planner({"template": "empty", "modules": ["+recipes", "+recipe_groceries", "+cooking"]})
    p.reasons = {"recipes": "needed by cooking", "recipe_groceries": "needed by cooking"}
    p.apply(p.turn_on_many(["recipes"]))
    assert p.draft.reasons == {"recipes": "asked"}
    assert p.turn_off_many(["cooking"]).spare == ("recipe_groceries",)


def test_template_modules_are_never_offered_as_no_longer_needed() -> None:
    change = planner().turn_off_many(["cooking"])
    assert "cooking" in change.off and change.spare == ()


def test_the_last_ai_provider_stays() -> None:
    p = planner({"template": "empty"})  # gemini only
    change = p.turn_off_many(["gemini"])
    assert change.off == () and change.kept[0][0] == "gemini"
    work = planner({"template": "work"})
    change = work.turn_off_many(["claude", "gemini", "openai_compatible"])
    # the first of them in the list stays
    assert change.off == ("gemini", "openai_compatible")
    assert [n for n, _ in change.kept] == ["claude"]


def test_a_template_module_switched_on_again_drops_its_reason() -> None:
    p = planner()
    p.apply(p.turn_off_many(["safeway"]))
    p.apply(p.turn_on_many(["safeway"]))
    assert p.draft.modules == {} and p.draft.reasons == {}


def test_undoing_the_last_switch_puts_the_draft_back() -> None:
    p = planner({"template": "empty"})
    p.apply(p.turn_on("travel"))
    p.draft.note(1, "turned on Travel times", None)
    before = p.draft.switches()
    p.apply(p.turn_on_many(["cooking"]))
    p.draft.note(1, "turned on Cooking", before)
    assert p.draft.can_undo_last()
    assert p.draft.undo_last() == "turned on Cooking"
    assert p.draft.modules == {"travel": True} and p.draft.reasons == {"travel": "asked"}
    assert not p.draft.can_undo_last()  # the one before kept no "before"
