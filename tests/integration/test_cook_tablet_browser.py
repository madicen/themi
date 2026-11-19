"""CK12: the tablet layout in a real (headless) Chrome: a tap on the step strip jumps to that
step, a timer's bar empties as it counts, an ingredient ticks the moment it's tapped, and
the footer says the screen stays awake only once the wake lock took. CK14: the mixes' Next
plays another track of the same kind. Skipped where Chrome isn't installed."""

from __future__ import annotations

import json

import pytest

from tests.integration.test_cook_screen_browser import short_timer, to_step_three
from tests.integration.test_session_page_browser import CHROME, page_in_chrome, until
from tests.scenarios.harness import Scenario
from themi import clock
from themi.core import keys

pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


async def test_a_tap_on_the_strip_jumps_to_that_step(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)  # Alfredo Sauce, on step 2 of 3
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=1180, height=820) as tab:  # fmt: skip
        strip = "[...document.querySelectorAll('.cook-steps li')]"
        marks = f"JSON.stringify({strip}.map(li => li.className))"
        assert json.loads(await tab.value(marks)) == ["done", "current", "later"]
        boxes = await tab.value(
            f"JSON.stringify({strip}.map(li => Math.round(li.getBoundingClientRect().top)))"
        )
        assert len(set(json.loads(boxes))) == 1  # one row across the top
        await tab.value(f"{strip}[2].querySelector('button').click()")
        count = "document.querySelector('.cook-count').textContent"
        assert await until(lambda: tab.value(f"({count}).startsWith('Step 3 of 3')"))
        assert await until(lambda: tab.value(f"{strip}[2].className === 'current'"))
    row = scenario.app.db.one("SELECT step FROM cooking_sessions ORDER BY id DESC")
    assert row is not None and row["step"] == 2


async def test_a_timers_bar_empties_as_it_counts(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    erin = scenario.member("Erin")
    session = cooking.current(erin)
    assert session is not None
    recipe = cooking.recipes.get(session.recipe_id)
    assert recipe is not None
    cooking.timers.start(erin, session, recipe, "2", 0.1)  # six seconds
    async with page_in_chrome(scenario, erin, ".cook-moves", width=1180, height=820) as tab:
        bar = "parseFloat(document.querySelector('.cook-bar span').style.width || '100')"
        assert await tab.value("document.querySelector('.cook-timer-of').textContent") == (
            "of 0:06 · remaining"
        )
        first = await until(lambda: tab.value(f"{bar} < 100 ? {bar} : 0"))
        assert first, "the bar never moved"
        assert await until(lambda: tab.value(f"{bar} < {first} - 10"))


async def test_an_ingredient_ticks_at_once(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=1180, height=820) as tab:  # fmt: skip
        line = "document.querySelector('.cook-amounts .cook-amount')"
        assert await tab.value(f"{line}.getAttribute('aria-pressed')") == "false"
        total = await tab.value("document.querySelectorAll('.cook-amounts .cook-amount').length")
        # the tick shows in the same moment, before the server answers
        ticked = await tab.value(
            f"(() => {{ {line}.click(); return {line}.getAttribute('aria-pressed'); }})()"
        )
        assert ticked == "true"
        added = "document.querySelector('.cook-added').textContent"
        assert await tab.value(added) == f"1 of {total} added"

        async def saved() -> bool:
            row = scenario.app.db.one("SELECT used FROM cooking_sessions ORDER BY id DESC")
            return row is not None and row["used"] != "[]"

        assert await until(saved)
        assert await until(lambda: tab.value(f"{line}.getAttribute('aria-pressed') === 'true'"))


async def test_the_footer_says_awake_only_with_the_wake_lock(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    await short_timer(scenario)
    with_lock = (
        "navigator.wakeLock = { request: () => Promise.resolve("
        "{ addEventListener: () => {}, release: () => Promise.resolve() }) };"
    )
    no_lock = "delete Navigator.prototype.wakeLock; delete navigator.wakeLock;"
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              before=with_lock) as tab:  # fmt: skip
        assert await until(lambda: tab.value("!document.querySelector('.cook-awake').hidden"))
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              before=no_lock) as tab:  # fmt: skip
        assert await tab.value("document.querySelector('.cook-awake').hidden")


QUIET_AUDIO = (  # no sound in a test: play() resolves, as after a tap
    "HTMLMediaElement.prototype.play = function () {"
    " Object.defineProperty(this, 'paused', {value: false, configurable: true});"
    " return Promise.resolve(); };"
)


async def test_next_plays_another_track_of_the_same_kind(scenario: Scenario) -> None:
    """Rain: a kind without chords, so Next never asks for a made mix (CK15b)."""
    from themi_home.body_double_music import set_sound

    clock.unfreeze()
    set_sound(scenario.app.store, scenario.member("Erin"), "rain")
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=1180, height=820) as tab:  # fmt: skip
        await tab.value(QUIET_AUDIO)
        lofi = json.loads(await tab.value(
            "JSON.stringify([...document.querySelectorAll('.cook-tracks[data-sound=rain] li')]"
            ".map(li => li.textContent))"
        ))  # fmt: skip
        assert len(lofi) >= 2
        name = "document.querySelector('[data-live=track-name]').textContent"
        src = "document.querySelector('.cook-music audio').getAttribute('src')"
        before = (await tab.value(name), await tab.value(src))
        assert before[0] in lofi
        assert await tab.value("document.querySelector('[data-live=playing]').textContent") == (
            "Ready to play"
        )
        for _ in range(4):  # never the same one twice running
            await tab.value("document.querySelector('.cook-track-next').click()")
            after = (await tab.value(name), await tab.value(src))
            assert after[0] in lofi and after != before
            before = after
        assert await until(lambda: tab.value(
            "document.querySelector('.session-play').getAttribute('aria-pressed') === 'true'"
        ))  # fmt: skip
        assert await tab.value("document.querySelector('[data-live=playing]').textContent") == (
            "Playing"
        )


async def test_a_mix_plays_live_from_its_settings(scenario: Scenario) -> None:
    """CK15a: a track with a mix and no file plays through mix.js: its chords in order at its
    tempo, and Pause stops it. (The audio context may stay suspended without a real tap;
    what's scheduled is still the mix's.)"""
    from themi_home.music_mix import Mix, Noise

    clock.unfreeze()
    # The first "Slow simmer"'s settings (F48a composed the built-in lofi on real instruments)
    mix = Mix("Slow simmer", "lofi", bpm=72, chords=("Dm9", "G13", "Cmaj9", "Am9"), strikes=2,
              decay=1.4, level=0.045, tone=2600, beat=True,
              noise=Noise("white", 0.012, highpass=3000))  # fmt: skip
    page = json.dumps(mix.for_page())
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=1180, height=820) as tab:  # fmt: skip
        assert await tab.value("window.themiMix.supported")
        plan = json.loads(await tab.value(
            f"JSON.stringify(window.themiMix.events({page}, 0, {mix.bar_seconds * 2}))"
        ))  # fmt: skip
        strikes = [e for e in plan if e["kind"] == "strike"]
        step = mix.bar_seconds / mix.strikes
        assert [round(e["at"], 3) for e in strikes] == [round(k * step, 3) for k in range(4)]
        assert [e["chord"] for e in strikes] == [0, 0, 1, 1]
        assert [e["at"] for e in plan if e["kind"] == "kick"][:2] == pytest.approx(
            [0, 2 * mix.bar_seconds / mix.beats]
        )
        await tab.value(
            "(() => { const li = document.createElement('li');"
            f" li.dataset.mix = JSON.stringify({page}); li.textContent = 'Mushroom simmer';"
            " document.querySelector('.cook-tracks[data-sound=lofi]').appendChild(li);"
            " window.themiCook.music.load(li, true); })()"
        )
        assert await tab.value("window.themiCook.music.player().mix.bpm") == mix.bpm
        assert await until(lambda: tab.value(
            "window.themiCook.music.player().scheduled.length > 0"
        ))  # fmt: skip
        assert await tab.value("window.themiCook.music.player().scheduled[0]") == 0
        name = "document.querySelector('[data-live=track-name]').textContent"
        assert await tab.value(name) == "Mushroom simmer"
        assert await tab.value("document.querySelector('.cook-play-label').textContent") == "Pause"
        assert await tab.value("document.querySelector('.cook-music audio').paused")
        await tab.value("document.querySelector('.session-play').click()")
        assert not await tab.value("window.themiCook.music.playing()")
        assert await tab.value("document.querySelector('[data-live=playing]').textContent") == (
            "Paused"
        )


async def test_play_makes_a_mix_for_the_recipe_and_it_takes_over(scenario: Scenario) -> None:
    """CK15b: the first Play of lofi starts a built-in track at once and asks for a mix made
    from the recipe's name; when it comes, it plays live in the built-in track's place."""
    from tests.unit.test_cook_mixes import SIMMER

    clock.unfreeze()
    await to_step_three(scenario)
    scenario.primary.queue_structured(SIMMER)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=1180, height=820) as tab:  # fmt: skip
        await tab.value(QUIET_AUDIO)
        name = "document.querySelector('[data-live=track-name]').textContent"
        assert await tab.value(name) != "Alfredo simmer"  # a built-in to start
        await tab.value("document.querySelector('.session-play').click()")
        assert await until(lambda: tab.value(f"({name}) === 'Alfredo simmer'"))
        assert await until(lambda: tab.value(
            "!!(window.themiCook.music.player() && window.themiCook.music.player().playing)"
        ))  # fmt: skip
        assert await tab.value("window.themiCook.music.player().mix.bpm") == SIMMER["bpm"]
        made = "document.querySelectorAll('.cook-tracks[data-sound=lofi] li[data-made]').length"
        assert await tab.value(made) == 1
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM music_mixes") == 1
