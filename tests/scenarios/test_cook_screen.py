"""CK1: the chat's card and the cook screen are two views of one session: a step typed in
Telegram shows on the page at its next poll. The clock starts Wednesday 21 October 2026,
9 am."""

from __future__ import annotations

import httpx

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines
from themi.core import keys


async def test_next_typed_in_telegram_shows_on_the_page(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    load(scenario.app.services)
    await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(lines(ALFREDO))
    await scenario.say("Erin", "Let's make the alfredo sauce")
    polled = (await site.get("/session/state")).json()
    assert (polled["phase"], polled["ahead"][0]["text"]) == ("ready", "soak the cashews (10 min)")
    await scenario.say("Erin", "done")  # the soak's done: on to gathering
    again = (await site.get("/session/state")).json()
    assert again["phase"] == "gather" and again["seq"] > polled["seq"]
    assert again["drawn"] != polled["drawn"]  # the page redraws
    page = (await site.get("/session/cook/view")).text
    assert "What it uses" in page and "1 Cup cashews" in page


PANCAKES = [
    "white whole wheat flour", "all-purpose flour", "baking powder", "cinnamon", "kosher salt",
    "almond milk", "applesauce", "vanilla extract",
]  # fmt: skip


async def test_pancakes_with_two_timers_at_once(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """CK3: the last step's two times, both started from the page, fire in order on the
    frozen clock; both show on the page, and each is cleared by a tap."""
    load(scenario.app.services)
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "pancakes", "scale": ""})
    scenario.primary.queue_structured(lines(PANCAKES))
    await scenario.say("Erin", "Let's make pancakes")
    scenario.primary.queue_structured({"jobs": []})
    for said in ("skip", "all here", "skip prep", "go to step 5"):
        await scenario.say("Erin", said)
    state = (await site.get("/session/state")).json()
    assert state["step"]["words"] == "Step 5 of 5"
    assert [o["label"] for o in state["offers"]] == ["Timer 2 min (2-3)", "Timer 1 min (1-2)"]

    async def act(action: str, **form: str) -> dict:
        seq = (await site.get("/session/state")).json()["seq"]
        response = await site.post(
            f"/session/cook/{state['id']}/act",
            headers={"X-Requested-With": "fetch"},
            data={"csrf": csrf, "action": action, "seq": str(seq), **form},
        )
        return response.json()

    for offer in state["offers"]:
        await act("timer", minutes=str(offer["minutes"]), step=offer["step"])
    shown = (await site.get("/session/state")).json()["timers"]
    assert [(t["label"], t["fired"]) for t in shown] == [("Step 5", False), ("Step 5", False)]
    await scenario.advance(minutes=1)
    await scenario.run_jobs()
    await scenario.app.outbox.flush()
    assert scenario.inbox("Erin")[-1] == "Time's up: 1 min for step 5 of Pancakes."
    shown = (await site.get("/session/state")).json()["timers"]
    assert [t["fired"] for t in shown] == [True, False]  # the 1 minute one first
    await scenario.advance(minutes=1)
    await scenario.run_jobs()
    await scenario.app.outbox.flush()
    assert scenario.inbox("Erin")[-1] == "Time's up: 2 min for step 5 of Pancakes."
    shown = (await site.get("/session/state")).json()["timers"]
    assert [t["fired"] for t in shown] == [True, True]
    page = (await site.get("/session/cook/view")).text
    assert page.count('data-fired="1"') == 2 and page.count("Time's up") == 2
    for timer in shown:
        await act("timer_clear", timer=str(timer["id"]))
    assert (await site.get("/session/state")).json()["timers"] == []


async def test_alfredo_preheat_offered_early_and_back_after_later(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """CK4: Alfredo Sauce baked over pasta. The oven in step 4 is offered from the start;
    [Later] hides it until step 3, where it comes back; [Done] and it's gone."""
    from tests.unit.test_cooking_look_ahead import BAKED, items

    load(scenario.app.services, BAKED)
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(items())
    await scenario.say("Erin", "Let's make the alfredo sauce")
    await scenario.tap("Erin", "Skip")  # "before anything else": not now
    state = (await site.get("/session/state")).json()
    assert state["strip"]["text"] == "Step 4 wants the oven at 400°F. Start it now?"
    page = (await site.get("/session/cook/view")).text
    assert "Step 4 wants the oven at 400°F" in page and 'value="ahead_later"' in page
    await site.post(
        f"/session/cook/{state['id']}/act",
        headers={"X-Requested-With": "fetch"},
        data={"csrf": csrf, "action": "ahead_later", "seq": str(state["seq"]),
              "key": state["strip"]["key"]},
    )  # fmt: skip
    scenario.primary.queue_structured({"jobs": []})
    for said, label in (("all here", "1"), ("next", "2")):
        await scenario.say("Erin", said)
        state = (await site.get("/session/state")).json()
        assert (state["step"]["label"], state["strip"]) == (label, None)
    await scenario.say("Erin", "next")
    state = (await site.get("/session/state")).json()
    assert state["step"]["label"] == "3" and state["strip"]["key"] == "preheat:3"
    await site.post(
        f"/session/cook/{state['id']}/act",
        headers={"X-Requested-With": "fetch"},
        data={"csrf": csrf, "action": "ahead_done", "seq": str(state["seq"]), "key": "preheat:3"},
    )
    assert (await site.get("/session/state")).json()["strip"] is None


async def test_how_much_garlic_asked_in_the_drawer(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """CK5: Ask Themi on the cook screen goes to the agent as typed chat does, with the
    recipe at the session's scale in its context as data; the answer shows in the drawer
    and in Telegram."""
    load(scenario.app.services)
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call(
        "start_cooking", {"recipe": "alfredo sauce", "scale": "double"}
    )
    scenario.primary.queue_structured(lines(ALFREDO))
    await scenario.say("Erin", "Let's make a double batch of the alfredo sauce")
    page = (await site.get("/session")).text
    assert "Ask Themi" in page and 'action="/session/cook/chat"' in page
    scenario.primary.queue_text("From the recipe: 4 garlic cloves, peeled and left whole.")
    state = (
        await site.post(
            "/session/cook/chat",
            headers={"X-Requested-With": "fetch"},
            data={"csrf": csrf, "text": "how much garlic?"},
        )
    ).json()
    asked = scenario.primary.requests[-1]
    context = str(asked.system) + str(getattr(asked, "messages", ""))
    assert '<data source="recipe Alfredo Sauce">' in context
    assert "4 garlic cloves, peeled and left whole" in context  # the scaled line
    assert [c["text"] for c in state["chat"]].count("how much garlic?") == 1  # logged once
    assert state["chat"][-2:] == [
        {"who": "you", "text": "how much garlic?"},
        {"who": "themi", "text": "From the recipe: 4 garlic cloves, peeled and left whole."},
    ]
    assert scenario.inbox("Erin")[-1] == "From the recipe: 4 garlic cloves, peeled and left whole."


async def test_pancakes_end_with_almond_milk_used_up_and_cleanup_company(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """CK6: after [All done], "Anything used up?" (the almond milk, out in the pantry), then
    company for cleanup: a Sprint Partner session, and /session turns to it."""
    load(scenario.app.services)
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "pancakes", "scale": ""})
    scenario.primary.queue_structured(lines(PANCAKES))
    await scenario.say("Erin", "Let's make pancakes")
    scenario.primary.queue_structured({"jobs": []})
    for said in ("skip", "all here", "go to step 5"):
        await scenario.say("Erin", said)
    state = (await site.get("/session/state")).json()

    async def act(action: str, **form: str) -> dict:
        seq = scenario.app.db.scalar("SELECT seq FROM cooking_sessions WHERE id = ?",
                                     (state["id"],))  # fmt: skip
        response = await site.post(
            f"/session/cook/{state['id']}/act",
            headers={"X-Requested-With": "fetch"},
            data={"csrf": csrf, "action": action, "seq": str(seq), **form},
        )
        return response.json()

    done = await act("finish")
    assert (done["phase"], done["line"], done["scene"]) == ("done", "All done. Enjoy it!",
                                                            "cheering")  # fmt: skip
    assert done["wrap"]["text"] == "Anything used up?"
    page = (await site.get("/session/cook/view")).text
    assert "Anything used up?" in page and 'value="almond milk"' in page
    used = await act("wrap_used", name="almond milk")
    assert used["said"] == "Almond milk: out."
    pantry = scenario.app.services.maybe(keys.pantry)
    assert pantry is not None and pantry.item("almond milk").status == "out"  # type: ignore[union-attr]
    offer = await act("wrap_used_done")
    assert offer["wrap"] == {"kind": "cleanup", "text": "Want company for cleanup?"}
    turned = await act("wrap_cleanup")
    assert turned.get("kind") != "cooking" and turned["label"] == "Clean up after Pancakes"
    assert turned["mode"] == "sprint"
    assert "cook-page" not in (await site.get("/session")).text  # the sprint's page now
    assert scenario.inbox("Erin")[-1].startswith("Sprint on: 25 minutes")  # the sprint's start
