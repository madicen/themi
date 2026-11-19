"""CK1: the cook screen's own script, in a real (headless) Chrome: [Next] moves the session,
and a timer counts down from the server's times. CK3: a fired timer's chime and pulse.
Skipped where Chrome isn't installed."""

from __future__ import annotations

import httpx
import pytest

from tests.fakes.spotify import FakeSpotify
from tests.fixtures.cookbook import load
from tests.integration.test_session_page_browser import CHROME, page_in_chrome, until
from tests.scenarios.harness import Scenario
from tests.scenarios.test_body_double import own_playlists
from tests.unit.test_cook_screen import ALFREDO, lines
from themi import clock
from themi.core import keys
from themi_home.music import SpotifyPlayback

pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


async def to_step_three(scenario: Scenario) -> None:
    load(scenario.app.services)
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    alfredo = next(r for r in cooking.recipes.all() if r.name == "Alfredo Sauce")
    scenario.primary.queue_structured(lines(ALFREDO))
    session = await cooking.start(scenario.member("Erin"), alfredo)
    scenario.primary.queue_structured({"jobs": []})
    for action in ("next", "next"):
        await cooking.advance(session, action)
    await cooking.advance(session, "goto:2")


async def test_next_on_the_page_moves_the_session(scenario: Scenario) -> None:
    clock.unfreeze()  # the browser keeps real time
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        count = "document.querySelector('.cook-count').textContent"
        assert (await tab.value(count)).startswith("Step 2 of 3")
        await tab.value("document.querySelector('form[data-move=next] button').click()")
        assert await until(lambda: tab.value(f"({count}).startsWith('Step 3 of 3')"))
        assert await tab.value("!!document.querySelector('form[data-move=finish]')")
    row = scenario.app.db.one("SELECT phase, step FROM cooking_sessions ORDER BY id DESC")
    assert row is not None and (row["phase"], row["step"]) == ("cook", 2)


async def test_a_timer_counts_down_from_the_servers_times(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        await tab.value("document.querySelector('form[data-move=next] button').click()")
        chip = "document.querySelector('.cook-offers .cook-chip')"
        assert await until(lambda: tab.value(f"!!{chip}"))
        await tab.value(f"{chip}.click()")
        left = "(document.querySelector('.cook-timer-left') || {}).textContent || ''"
        first = await until(lambda: tab.value(f"(({left}).match(/^9:5\\d$/) || [''])[0]"))
        assert first, "the timer never showed counting down from 10:00"
        later = await until(lambda: tab.value(f"({left}) !== '{first}' ? ({left}) : ''"), 4)
        assert later and later < first


async def short_timer(scenario: Scenario) -> int:
    """A timer that ends in a moment, started as the page's chip would start one."""
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    session = cooking.current(scenario.member("Erin"))
    assert session is not None
    recipe = cooking.recipes.get(session.recipe_id)
    assert recipe is not None
    cooking.timers.start(scenario.member("Erin"), session, recipe, "3", 0.01)
    return session.id


async def fire(scenario: Scenario) -> None:
    async def fired() -> bool:
        await scenario.run_jobs()
        return bool(scenario.app.db.scalar("SELECT COUNT(*) FROM cooking_timers "
                                           "WHERE fired_at IS NOT NULL"))  # fmt: skip

    assert await until(fired)


FAKE_AUDIO = (
    "window.themiCook.playChime = function (v) { window.chimes = (window.chimes || 0) + 1;"
    " window.chimeVolume = v; }; window.themiCook.alertEvery = 400;"
)


async def test_a_fired_timer_chimes_and_pulses_until_tapped(scenario: Scenario) -> None:
    """CK3: when fired_at appears, a chime (faked here) and a slow pulse, again and again,
    until the card is tapped."""
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        await tab.value(FAKE_AUDIO)
        await short_timer(scenario)
        await fire(scenario)
        await tab.value("window.themiCook.poll()")
        assert await until(lambda: tab.value("(window.chimes || 0) >= 3"))  # repeating
        assert await tab.value("window.chimeVolume") == 70
        assert await tab.value("document.querySelector('.cook-pulse').classList.contains('on')")
        assert await tab.value("document.body.classList.contains('cook-alerting')")
        assert (
            await tab.value("getComputedStyle(document.querySelector('.cook-pulse')).animationName")
            == "cook-pulse"
        )
        await tab.value("document.querySelector('.cook-timer-done').click()")
        assert await until(lambda: tab.value("!document.querySelector('.cook-timer[data-fired]')"))
        stopped = await tab.value("window.chimes")
        rang = await until(lambda: tab.value(f"window.chimes > {stopped}"), 1.5)
        assert rang is None  # three more rings in that time, had it gone on
        assert not await tab.value("document.body.classList.contains('cook-alerting')")


async def test_reduced_motion_is_a_steady_border(scenario: Scenario) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        reduce = [{"name": "prefers-reduced-motion", "value": "reduce"}]
        await tab.call("Emulation.setEmulatedMedia", features=reduce)
        await tab.value(FAKE_AUDIO)
        await short_timer(scenario)
        await fire(scenario)
        await tab.value("window.themiCook.poll()")
        assert await until(lambda: tab.value("document.body.classList.contains('cook-alerting')"))
        pulse = "getComputedStyle(document.querySelector('.cook-pulse')).display"
        assert await tab.value(pulse) == "none"
        shadow = await tab.value("getComputedStyle(document.body).boxShadow")
        assert "inset" in shadow and "12px" in shadow
        assert await tab.value("(window.chimes || 0) >= 1")  # the chime still sounds


# CK7: the main screen (a tablet propped up in landscape), a tablet upright, and a phone.
# CK12: and an 11-inch tablet in landscape (1180 x 820).
LAYOUT = (
    "(() => {"
    " const w = window.innerWidth, out = [];"
    " const wide = document.documentElement.scrollWidth;"
    " if (wide > w) out.push('scrolls ' + wide);"
    " for (const el of document.querySelectorAll('.cook *')) {"
    "  const r = el.getBoundingClientRect();"
    "  if (!r.width || !r.height) continue;"
    "  if (el.closest('[hidden], .cook-drawer, details:not([open]) > :not(summary)')) continue;"
    "  if (el.closest('.session-scene svg')) continue;"  # the art, clipped by its frame
    "  if (r.right > w + 1 || r.left < -1)"
    "   out.push((el.className || el.tagName) + ' ' + Math.round(r.left)"
    "            + '-' + Math.round(r.right));"
    " }"
    " const text = parseFloat(getComputedStyle(document.querySelector('.cook-text')).fontSize);"
    " if (text < 28) out.push('step text ' + text);"
    " for (const b of document.querySelectorAll('.cook-moves button, .cook-timer-moves button')) {"
    "  if (b.getBoundingClientRect().height < 64) out.push('short button ' + b.textContent);"
    " }"
    " return out.join('; ');"
    "})()"
)


@pytest.mark.parametrize(("width", "height"), [(1180, 820), (1024, 768), (768, 1024), (390, 844)])
async def test_the_layout_fits(scenario: Scenario, width: int, height: int) -> None:
    clock.unfreeze()
    await to_step_three(scenario)
    cooking = scenario.app.services.maybe(keys.cooking)
    assert cooking is not None
    session = cooking.current(scenario.member("Erin"))
    assert session is not None
    await cooking.advance(session, "next")  # step 3: a timer chip
    await short_timer(scenario)  # and a timer on the rail
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=width, height=height) as tab:  # fmt: skip
        assert await tab.value("window.innerWidth") == width
        assert await tab.value(LAYOUT) == ""
        step = await tab.value(
            "JSON.stringify(document.querySelector('.cook-step').getBoundingClientRect())"
        )
        rail = await tab.value(
            "JSON.stringify(document.querySelector('.cook-rail').getBoundingClientRect())"
        )
        import json

        step_box, rail_box = json.loads(step), json.loads(rail)
        if width > height:  # landscape: the rail beside the step
            assert rail_box["left"] >= step_box["right"] - 1
        else:  # portrait: stacked
            assert rail_box["top"] >= step_box["bottom"] - 1
        await tab.value("document.querySelector('.cook-all-open').click()")
        assert await tab.value(LAYOUT) == ""  # the drawer open too


async def test_the_biggest_text_fits_a_phone(scenario: Scenario) -> None:
    """CK7: 200% text, the whole list of steps and the kitchen theme, at 390 px."""
    from themi_home.cooking import CookingPreferences

    clock.unfreeze()
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(
        erin, erin.id, CookingPreferences,
        cooking_text_size=200, cooking_theme="kitchen", cooking_steps_view="all",
    )  # fmt: skip
    await to_step_three(scenario)
    async with page_in_chrome(scenario, erin, ".cook-moves", width=390, height=844) as tab:
        assert await tab.value("document.body.dataset.theme") == "kitchen"
        assert await tab.value("!!document.querySelector('.cook-all-steps li.current')")
        assert await tab.value(LAYOUT) == ""
        await tab.value("document.querySelector('.cook-size button[value=down]').click()")
        assert await until(lambda: tab.value("document.body.dataset.textSize === '170'"))
    # Bug 2026-11-08: since A+ scales the whole screen, the Back and All done buttons ran off
    # CI's Chrome by 3 px at 390 (its fonts are wider). A smaller phone, with room to spare.
    scenario.app.store.save_preferences(erin, erin.id, CookingPreferences, cooking_text_size=200)
    async with page_in_chrome(scenario, erin, ".cook-moves", width=360, height=780) as tab:
        assert await tab.value(LAYOUT) == ""


SIZES = (
    "JSON.stringify(['.cook-text', '.cook-count', '.cook-recipe', '.cook-moves button']"
    ".map(s => parseFloat(getComputedStyle(document.querySelector(s)).fontSize)))"
)


async def test_a_minus_and_a_plus_change_what_shows(scenario: Scenario) -> None:
    """Bug 2026-11-08: A- and A+ saved the size but the screen hardly changed: A- did
    nothing to the step (held at its 28 px floor), and the count, the recipe's name and the
    buttons never scaled at all. Every size on the screen follows them now."""
    import json

    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        start = json.loads(await tab.value(SIZES))
        await tab.value("document.querySelector('.cook-size button[value=down]').click()")
        assert await until(lambda: tab.value("document.body.dataset.textSize === '90'"))
        smaller = json.loads(await tab.value(SIZES))
        assert all(a < b for a, b in zip(smaller, start, strict=True)), (start, smaller)
        assert smaller[0] >= 28  # the step text keeps its floor
        for size in ("100", "120"):
            await tab.value("document.querySelector('.cook-size button[value=up]').click()")
            assert await until(
                lambda s=size: tab.value(f"document.body.dataset.textSize === '{s}'")
            )
        bigger = json.loads(await tab.value(SIZES))
        assert all(a > b for a, b in zip(bigger, start, strict=True)), (start, bigger)


FAKE_RECOGNIZER = (
    "window.webkitSpeechRecognition = function () {"
    " const rec = this;"
    " rec.start = function () { window.listened = (window.listened || 0) + 1;"
    "  setTimeout(function () {"
    "   rec.onresult({ results: [[{ transcript: window.nextWords || 'next' }]] });"
    "   rec.onend();"
    "  }, 50); };"
    " rec.stop = function () {};"
    "}; window.SpeechRecognition = undefined; window.themiCook.setupVoice();"
)


async def test_push_to_talk(scenario: Scenario) -> None:
    """CK8: the mic is hidden without speech recognition or without the setting; with both
    (a faked recognizer here), "next" heard moves the session."""
    from themi_home.cooking import CookingPreferences

    clock.unfreeze()
    erin = scenario.member("Erin")
    await to_step_three(scenario)  # step 2, voice off
    async with page_in_chrome(scenario, erin, ".cook-moves") as tab:
        assert await tab.value("!document.querySelector('.cook-mic')")  # off: no button at all
    scenario.app.store.save_preferences(erin, erin.id, CookingPreferences, cooking_voice=True)
    async with page_in_chrome(scenario, erin, ".cook-moves") as tab:
        mic = "document.querySelector('.cook-mic')"
        await tab.value("window.SpeechRecognition = undefined;"
                        " window.webkitSpeechRecognition = undefined;"
                        " window.themiCook.setupVoice()")  # fmt: skip
        assert await tab.value(f"{mic}.hidden")  # no speech recognition: hidden
        await tab.value(FAKE_RECOGNIZER)
        assert await tab.value(f"!{mic}.hidden")
        count = "document.querySelector('.cook-count').textContent"
        assert (await tab.value(count)).startswith("Step 2 of 3")
        await tab.value(f"{mic}.dispatchEvent(new PointerEvent('pointerdown'));"
                        f" {mic}.dispatchEvent(new PointerEvent('pointerup'))")  # fmt: skip
        assert await until(lambda: tab.value(f"({count}).startsWith('Step 3 of 3')"))
        heard = "document.querySelector('.cook-heard').textContent"
        assert await tab.value(heard) == "“next”"
        assert await tab.value("window.listened") == 1  # one phrase a press


HELD_RECOGNIZER = (
    "window.stopped = 0; window.webkitSpeechRecognition = function () {"
    " const rec = this; window.rec = rec;"
    " rec.start = function () { window.listened = (window.listened || 0) + 1; };"
    " rec.stop = function () { window.stopped += 1;"
    "  rec.onresult({ results: [[{ transcript: 'next' }]] }); rec.onend(); };"
    "}; window.SpeechRecognition = undefined; window.themiCook.setupVoice();"
)


async def test_a_long_press_talks_and_never_selects(scenario: Scenario) -> None:
    """F45c (bug #214): on an iPhone a long press on "Hold to talk" selected "Hold", the
    press was cancelled, and the recognizer was aborted with nothing said."""
    from themi_home.cooking import CookingPreferences

    clock.unfreeze()
    erin = scenario.member("Erin")
    await to_step_three(scenario)
    scenario.app.store.save_preferences(erin, erin.id, CookingPreferences, cooking_voice=True)
    async with page_in_chrome(scenario, erin, ".cook-moves") as tab:
        mic = "document.querySelector('.cook-mic')"
        await tab.value(HELD_RECOGNIZER)
        assert await tab.value(f"getComputedStyle({mic}).userSelect") == "none"
        assert await tab.value(f"getComputedStyle({mic}).touchAction") == "none"
        menu = "new MouseEvent('contextmenu', {bubbles: true, cancelable: true})"
        assert await tab.value(f"!{mic}.dispatchEvent({menu})")  # prevented
        select = "new Event('selectstart', {bubbles: true, cancelable: true})"
        assert await tab.value(f"!{mic}.dispatchEvent({select})")
        # a press the browser cancels (iOS starting a selection) stops listening
        await tab.value(
            f"{mic}.dispatchEvent(new PointerEvent('pointerdown', {{cancelable: true}}))"
        )
        assert await tab.value(f"{mic}.getAttribute('aria-pressed')") == "true"
        assert "Listening" in await tab.value(f"{mic}.textContent")
        await tab.value(f"{mic}.dispatchEvent(new PointerEvent('pointercancel'))")
        assert await tab.value("window.stopped") == 1
        assert await tab.value("window.getSelection().toString()") == ""
        count = "document.querySelector('.cook-count').textContent"
        assert await until(lambda: tab.value(f"({count}).startsWith('Step 3 of 3')"))
        assert "Hold to talk" in await tab.value(f"{mic}.textContent")
        # an aborted recognizer says so, under the button
        await tab.value(
            f"{mic}.dispatchEvent(new PointerEvent('pointerdown', {{cancelable: true}}))"
        )
        await tab.value("window.rec.onerror({error: 'aborted'}); window.rec.onend()")
        heard = "document.querySelector('.cook-heard').textContent"
        assert await tab.value(heard) == "Didn't catch that. Tap to try again."
        await tab.value("window.rec.onerror({error: 'not-allowed'})")
        assert await tab.value(heard) == "The microphone isn't allowed for this page."


async def test_spotify_on_the_cook_screen_plays_and_pauses_once_a_tap(
    scenario: Scenario, site: httpx.AsyncClient, fake_spotify: FakeSpotify
) -> None:
    """Michael, 2026-11-18: the cook screen's Spotify Play and Pause seemed not to work. In a
    real browser each tap reaches Spotify once, liked songs first, and says what happened."""
    clock.unfreeze()
    await own_playlists(scenario, site, fake_spotify)
    fake_spotify.add_liked("Song 1")
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves") as tab:
        await tab.value("document.getElementById('cook-tab-spotify').click()")
        assert not await tab.value("document.getElementById('cook-spotify').hidden")
        said = "document.querySelector('.cook-spotify .session-spotify-said').textContent"
        await tab.value("document.querySelector('.cook-spotify button[value=play]').click()")
        assert await until(lambda: tab.value(f"({said}).startsWith('Playing your liked songs')"))
        # F47a: Shuffle, ticked while it plays, reaches Spotify at once
        box = "document.querySelector('.cook-spotify input[type=checkbox][name=shuffle]')"
        await tab.value(f"{box}.click()")
        assert await until(lambda: tab.value(f"({said}).startsWith('Shuffle on')"))
        assert fake_spotify.shuffle is True
        await tab.value("document.querySelector('.cook-spotify button[value=pause]').click()")
        assert await until(lambda: tab.value(f"({said}) === 'Paused.'"))
        await until(lambda: tab.value("false"), 1)  # a second post, had there been one
    assert fake_spotify.calls.count("PUT /v1/me/player/play") == 1
    assert scenario.app.store.preferences(
        scenario.member("Erin").id, SpotifyPlayback
    ).spotify_shuffle  # kept for next time
    assert fake_spotify.calls.count("PUT /v1/me/player/pause") == 1
    assert fake_spotify.paused


SCENE = (
    "(() => {"
    " const box = e => JSON.parse(JSON.stringify(e.getBoundingClientRect()));"
    " const scene = document.querySelector('.cook-scene');"
    " return JSON.stringify({"
    "  scene: box(scene), cham: box(scene.querySelector('.cham')),"
    "  feet: box(scene.querySelector('.cham-foot')),"
    "  stool: box(scene.querySelector('.scene-cooking .scene-stool')),"
    "  mood: box(document.querySelector('.cook-company-side')),"
    " });"
    "})()"
)


@pytest.mark.parametrize(("width", "height"), [(390, 844), (768, 1024), (1440, 900)])
async def test_themi_stays_on_the_stool(scenario: Scenario, width: int, height: int) -> None:
    """F49e (bugs #222, #226): cut off on an iPhone; floating off the stool on a computer."""
    import base64
    import json
    import os

    clock.unfreeze()
    await to_step_three(scenario)
    async with page_in_chrome(scenario, scenario.member("Erin"), ".cook-moves",
                              width=width, height=height) as tab:  # fmt: skip
        await tab.value("document.querySelector('.cook-company').scrollIntoView()")
        found = json.loads(await tab.value(SCENE))
        if folder := os.environ.get("THEMI_SHOTS"):  # to look at by eye
            shot = await tab.call("Page.captureScreenshot", format="png")
            data = base64.b64decode(shot["result"]["data"])
            with open(os.path.join(folder, f"cook-scene-{width}.png"), "wb") as f:
                f.write(data)
    scene, cham, feet, stool = found["scene"], found["cham"], found["feet"], found["stool"]
    assert scene["left"] - 1 <= cham["left"] and cham["right"] <= scene["right"] + 1
    assert scene["top"] - 1 <= cham["top"] and cham["bottom"] <= scene["bottom"] + 1
    assert abs(feet["bottom"] - stool["top"]) <= scene["height"] * 0.05  # on the seat
    middle = (feet["left"] + feet["right"]) / 2
    assert stool["left"] <= middle <= stool["right"]
    assert scene["height"] <= 145
    if width < 600:  # a phone: above the line and music, not a column beside them
        assert scene["bottom"] <= found["mood"]["top"] + 1
