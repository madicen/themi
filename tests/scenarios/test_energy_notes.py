"""Energy remarks get recorded (Shadow Calendar inputs): by the model, or caught when it
doesn't. From the Shadow Calendar review: Erin's "medium energy day" left no trace."""

from tests.scenarios.harness import Scenario


def signals(scenario: Scenario, name: str) -> list[tuple[str, float]]:
    return [
        (r["source"], r["value"])
        for r in scenario.app.db.query(
            "SELECT source, value FROM energy_signals WHERE member_id = ? "
            "AND source IN ('text_note', 'day_level') ORDER BY id",
            (scenario.member(name).id,),
        )
    ]


async def test_the_model_can_record_a_day_level(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("log_energy_level", {"level": "medium", "note": "said so"})
    scenario.primary.queue_text("Got it, a medium day.")
    await scenario.say("Erin", "It's a medium energy day")
    assert signals(scenario, "Erin") == [("day_level", 0.0)]


async def test_a_clear_day_level_the_model_skipped_is_still_recorded(scenario: Scenario) -> None:
    scenario.primary.queue_text("Medium level: wipe the sink, clean the toilet, vacuum, mop.")
    await scenario.say(
        "Erin", "The bathroom is due and it's a medium energy day. What should I do?"
    )
    assert signals(scenario, "Erin") == [("day_level", 0.0)]


async def test_a_clear_drain_the_model_skipped_is_still_recorded(scenario: Scenario) -> None:
    scenario.primary.queue_text("That sounds like a lot.")
    await scenario.say("Husband", "Work was brutal, I'm wiped out")
    ((source, value),) = signals(scenario, "Husband")
    assert source == "text_note" and value < 0


async def test_nothing_is_recorded_twice(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("log_energy_note", {"effect": -2, "note": "wiped"})
    scenario.primary.queue_text("Rest up.")
    await scenario.say("Erin", "I'm wiped out")
    assert signals(scenario, "Erin") == [("text_note", -2.0)]


async def test_ordinary_feelings_about_things_arent_energy(scenario: Scenario) -> None:
    scenario.primary.queue_text("Great.")
    await scenario.say("Erin", "I feel good about that plan for the kitchen")
    assert signals(scenario, "Erin") == []


async def test_the_privacy_switch_is_respected(scenario: Scenario) -> None:
    from themi.accounts import SYSTEM

    scenario.app.store.update_settings(
        SYSTEM, scenario.member("Erin").id, tracking={"text_notes": False}
    )
    scenario.primary.queue_text("Okay.")
    await scenario.say("Erin", "It's a low energy day")
    assert signals(scenario, "Erin") == []


def test_the_prompt_asks_for_energy_remarks() -> None:
    from tests.fakes.prompt import FAMILY_SYSTEM as STABLE_SYSTEM

    assert "log_energy_note" in STABLE_SYSTEM and "log_energy_level" in STABLE_SYSTEM


async def test_energy_said_about_the_partner_isnt_theirs(scenario: Scenario) -> None:
    """Bug #126: Michael's "Erin is at zero energy" is about her, and her energy isn't his to
    record, by the model or the backstop."""
    scenario.primary.queue_tool_call("log_energy_level", {"level": "low", "note": "zero energy"})
    scenario.primary.queue_text("I'm sorry to hear it.")
    await scenario.say("Husband", "Erin is at zero energy")
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", "She\u2019s having a low energy day")
    assert signals(scenario, "Husband") == [] and signals(scenario, "Erin") == []
    scenario.primary.queue_text("Okay.")
    await scenario.say("Husband", "Erin's fine, but I'm having a low energy day")
    assert signals(scenario, "Husband") == [("day_level", -1.0)]
