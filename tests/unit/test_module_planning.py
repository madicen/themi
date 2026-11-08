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
    # 35a: takeout needs spending, so it goes with it
    assert config.removed == ("spending", "takeout") and config.added == ()
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
