"""CK15b: a mix made from the recipe's name. One cheap model call picks a few settings, the
ranges keep them soft, and the mix is kept by recipe and kind. The clock starts Wednesday
21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_company import cooking, start  # noqa: F401 - the fixture
from themi.ai.settings import AITask
from themi_home.cooking import Cooking
from themi_home.cooking_mixes import ASKS, MIX_SYSTEM, mix_from_answer
from themi_home.music_mix import MixRefused

SIMMER = {"name": "Alfredo simmer", "bpm": 74, "beats": 4,
          "chords": ["Dm9", "G13", "Cmaj9", "Am9"], "strikes": 2, "decay": 1.3}  # fmt: skip
BRIGHT = {**SIMMER, "name": "Garlic glow", "chords": ["Fmaj7", "Em7", "Dm7", "Cmaj7"]}


def test_an_answer_becomes_a_mix_of_its_kind() -> None:
    lofi = mix_from_answer("lofi", SIMMER)
    assert (lofi.kind, lofi.beat, lofi.bpm, lofi.bars) == ("lofi", True, 74, 16)
    assert lofi.noise is not None and lofi.noise.color == "white"  # the crackle
    piano = mix_from_answer("soft_piano", {**SIMMER, "chords": ["Em9", "Cmaj7", "G"]})
    assert (piano.beat, piano.echoes, piano.bars) == (False, ((200, 0.25),), 15)


@pytest.mark.parametrize(
    "answer",
    [
        {**SIMMER, "bpm": 140},
        {**SIMMER, "chords": ["Dm9", "C#dim13"]},
        {**SIMMER, "strikes": 6},
        {**SIMMER, "decay": "long"},
        {k: v for k, v in SIMMER.items() if k != "chords"},
    ],
)
def test_a_bad_answer_is_refused(answer: dict) -> None:
    with pytest.raises(MixRefused):
        mix_from_answer("lofi", answer)


def mix_calls(scenario: Scenario) -> list:
    return [r for r in scenario.primary.requests if r.op == "structured" and r.system == MIX_SYSTEM]


async def ask(site: httpx.AsyncClient, csrf: str, kind: str = "lofi", fresh: bool = False) -> dict:
    form = {"csrf": csrf, "kind": kind, "fresh": "1" if fresh else "0"}
    answer = await site.post("/session/cook/mix", data=form)
    assert answer.status_code == 200
    return answer.json()["mix"]


async def test_a_mix_is_made_once_and_kept_for_the_recipe(
    scenario: Scenario,
    site: httpx.AsyncClient,
    cooking: Cooking,  # noqa: F811
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await start(scenario, cooking)
    scenario.primary.queue_structured(SIMMER)
    made = await ask(site, csrf)
    assert made["name"] == "Alfredo simmer" and made["page"]["bpm"] == 74
    assert made["page"]["chords"][0] == ["D3", "F4", "A4", "E5"]  # notes, for the player
    (call,) = mix_calls(scenario)
    assert '<data source="recipe name">\nAlfredo Sauce\n</data>' in call.prompt
    assert "lofi" in call.prompt and "Erin" not in call.prompt  # the name and the kind only
    again = await ask(site, csrf)
    assert again == made and len(mix_calls(scenario)) == 1  # kept: no second call
    # the card lists it first in its kind, to be played live
    page = (await site.get("/session")).text
    lofi = page.split('data-sound="lofi" data-musical="1" hidden>')[1].split("</ul>")[0]
    assert (
        lofi.startswith("<li data-mix='")
        and f'data-made="{made["id"]}">Alfredo simmer</li>' in lofi
    )
    state = (await site.get("/session/state")).json()["music"]
    assert [m["name"] for m in state["mixes"]["lofi"]] == ["Alfredo simmer"]


async def test_next_asks_for_a_fresh_one_a_few_times_a_session(
    scenario: Scenario,
    site: httpx.AsyncClient,
    cooking: Cooking,  # noqa: F811
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await start(scenario, cooking)
    scenario.primary.queue_structured(SIMMER)
    first = await ask(site, csrf)
    scenario.primary.queue_structured(BRIGHT)
    fresh = await ask(site, csrf, fresh=True)
    assert fresh["name"] == "Garlic glow" and fresh["id"] != first["id"]
    assert "Already made for it (choose something different): Alfredo simmer" in (
        mix_calls(scenario)[-1].prompt
    )
    for _ in range(ASKS - 2):
        scenario.primary.queue_structured(BRIGHT)
        assert await ask(site, csrf, fresh=True)
    assert await ask(site, csrf, fresh=True) is None  # past the session's asks: no call
    assert len(mix_calls(scenario)) == ASKS
    kept = cooking.mixes.kept(cooking.current(scenario.member("Erin")).recipe_id)  # type: ignore[union-attr]
    assert kept["lofi"][0]["name"] == "Alfredo simmer"  # the one it starts with next time


async def test_a_bad_answer_or_no_answer_falls_back_quietly(
    scenario: Scenario,
    site: httpx.AsyncClient,
    cooking: Cooking,  # noqa: F811
) -> None:
    from themi.ai.errors import PermanentError

    csrf = await sign_in(scenario, site, "Erin")
    await start(scenario, cooking)
    scenario.primary.queue_structured({**SIMMER, "bpm": 140})
    assert await ask(site, csrf) is None
    for model in (scenario.primary, scenario.fallback):  # the chain's both refuse
        model.queue_error(PermanentError("no"), op="structured")
    assert await ask(site, csrf) is None
    assert await ask(site, csrf, kind="rain") is None  # noise has no chords to choose
    assert (
        len(mix_calls(scenario))
        + len([r for r in scenario.fallback.requests if r.system == MIX_SYSTEM])
        == 3
    )
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM music_mixes") == 0


async def test_everyone_has_a_route_for_it(scenario: Scenario) -> None:
    settings = scenario.app.services.router.settings
    for name in ("Erin", "Husband"):
        member = scenario.member(name)
        assert settings.resolve(member.id, AITask.MUSIC_MIX) == settings.resolve(
            member.id, AITask.STRUCTURED_MISC
        )
