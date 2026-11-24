"""F60e (Michael's idea #263): the body double on the wall: start a session and run it there.
The frame is shared, so it asks who's this first (the same choice as Talk to Themi); a
session started there sends its start message to Telegram as one from chat, and a tap on the
wall edits that message. The scenario starts Wednesday 21 October 2026, 9 am, Los Angeles."""

from __future__ import annotations

import re

from tests.integration.test_wall_list_views import get, post
from tests.integration.test_wall_screen import screen, step, task, wall, words
from tests.scenarios.harness import Scenario
from tests.scenarios.test_body_double import start
from themi.core import keys

__all__ = ["wall"]  # the fixture


def session_rows(s: Scenario) -> list[dict[str, object]]:
    return s.app.db.query("SELECT * FROM body_double_sessions ORDER BY id")


async def test_the_top_bar_offers_it_and_asks_whos_this(wall: Scenario) -> None:
    page = await screen(wall)
    assert 'hx-get="/wall/focus"' in page and "Body double" in page
    sheet = words((await get(wall, "/wall/focus")).text)
    assert "Who&#39;s this?" in sheet and "Erin" in sheet and "Husband" in sheet


async def test_the_pick_offers_their_tasks_and_starts_a_session(wall: Scenario) -> None:
    husband = wall.member("Husband")
    birdcage = await task(wall, "Husband", "Cover the birdcage", due=wall.today())
    sheet = (await get(wall, f"/wall/focus?member={husband.id}")).text
    assert "What are you working on?" in sheet and "Cover the birdcage" in sheet
    assert f'value="task:{birdcage.id}"' in sheet
    assert 'data-close-after="120"' in sheet

    wall.primary.queue_structured({"category": "chores"})  # the job's kind, asked once
    running = (
        await post(wall, "/wall/focus/start", member=str(husband.id),
                   what=f"task:{birdcage.id}", mode="silent", minutes="0")
    ).text  # fmt: skip
    (row,) = session_rows(wall)
    assert row["member_id"] == husband.id and row["task_id"] == birdcage.id
    assert row["mode"] == "silent"
    sent = wall.app.db.query("SELECT text FROM outbox WHERE member_id = ?", (husband.id,))
    assert sent and sent[-1]["text"].startswith("I'm here.")  # to Telegram, as from chat
    assert "data-focus-running" in running and 'data-close-after="0"' in running
    assert 'class="session-scene focus-scene"' in running and "Done" in running


async def test_done_on_the_wall_ends_it_and_edits_the_chat_message(wall: Scenario) -> None:
    husband = wall.member("Husband")
    await post(wall, "/wall/focus/start", member=str(husband.id), what="typed",
               typed="the dishes", mode="silent", minutes="0")  # fmt: skip
    await wall.app.outbox.flush()
    (row,) = session_rows(wall)
    bd = wall.app.services.get(keys.body_double)
    session = bd.get(int(row["id"]))  # type: ignore[arg-type]
    assert session is not None
    edits = len(wall.edits("Husband"))
    over = (
        await post(wall, "/wall/focus/act", member=str(husband.id), session=str(session.id),
                   seq=str(session.seq), action="done", mode="")
    ).text  # fmt: skip
    assert bd.current(husband) is None
    assert "data-focus-finished" in over and "the dishes" in over
    assert len(wall.edits("Husband")) > edits  # the Telegram message says it too


async def test_an_old_tap_or_someone_elses_session_does_nothing(wall: Scenario) -> None:
    erin, husband = wall.member("Erin"), wall.member("Husband")
    await post(wall, "/wall/focus/start", member=str(husband.id), what="typed",
               typed="the dishes", mode="silent", minutes="0")  # fmt: skip
    (row,) = session_rows(wall)
    bd = wall.app.services.get(keys.body_double)
    session = bd.get(int(row["id"]))  # type: ignore[arg-type]
    assert session is not None
    theirs = await post(wall, "/wall/focus/act", member=str(erin.id), session=str(session.id),
                        seq=str(session.seq), action="done")  # fmt: skip
    assert theirs.status_code == 404
    await post(wall, "/wall/focus/act", member=str(husband.id), session=str(session.id),
               seq=str(session.seq - 1), action="done")  # fmt: skip
    assert bd.current(husband) is not None  # an old seq does nothing


async def test_a_session_from_telegram_shows_in_her_column_and_opens(wall: Scenario) -> None:
    erin = wall.member("Erin")
    await start(
        wall, "Sit with me while I do the dishes", mode="quiet", minutes=30, what="the dishes"
    )
    page = await screen(wall)
    chip = re.search(r"<button[^>]*wall-focus-chip[^>]*>([^<]+)</button>", page)
    assert chip is not None and chip[1].startswith("Body double · ")
    assert f"/wall/focus?member={erin.id}" in page
    running = (await get(wall, f"/wall/focus?member={erin.id}")).text
    assert "data-focus-running" in running and "the dishes" in running.lower()
    live = (await get(wall, f"/wall/focus/live?member={erin.id}")).text
    assert "focus-timer" in live


async def test_no_chip_without_a_session(wall: Scenario) -> None:
    assert "wall-focus-chip" not in await screen(wall)


async def test_strangers_and_no_one_are_refused(wall: Scenario) -> None:
    assert (await post(wall, "/wall/focus/start", what="typed", typed="x")).status_code == 400
    assert (
        await post(wall, "/wall/focus/start", member="999", what="typed", typed="x")
    ).status_code == 404
    assert (await get(wall, "/wall/focus?member=999")).status_code == 404


async def test_burnout_mode_says_why_it_didnt_start(wall: Scenario) -> None:
    husband = wall.member("Husband")
    burnout = wall.app.services.get(keys.burnout)
    await burnout.start(husband)
    assert burnout.current(husband)
    sheet = (
        await post(wall, "/wall/focus/start", member=str(husband.id), what="typed",
                   typed="the dishes", mode="", minutes="0")
    ).text  # fmt: skip
    assert "Not started: burnout mode is on" in sheet
    assert session_rows(wall) == []


async def test_a_routine_with_something_open_is_offered_and_goes_step_by_step(
    wall: Scenario,
) -> None:
    husband = wall.member("Husband")
    step(wall, "Husband", "Evening", "Take Meds")
    routines = wall.app.services.get(keys.routines)
    evening = routines.find(husband, "Evening")
    assert evening is not None
    sheet = (await get(wall, f"/wall/focus?member={husband.id}")).text
    assert f'value="routine:{evening.id}"' in sheet and "Evening routine" in sheet
    running = (
        await post(wall, "/wall/focus/start", member=str(husband.id),
                   what=f"routine:{evening.id}", mode="", minutes="0")
    ).text  # fmt: skip
    (row,) = session_rows(wall)
    assert row["mode"] == "guided" and row["routine_id"] == evening.id
    assert "Take Meds" in running


# ----- step pictures and the built-in loop on the wall -----------------------------------


async def guided_kitchen(wall: Scenario, owner: str = "Husband") -> int:
    member = wall.member(owner)
    board = wall.app.services.get(keys.taskboard)
    made = await board.create(member, "Clean the kitchen", "physical", 3)
    await board.update(made.id, member, steps=["Clear the counter", "Sweep"])
    bd = wall.app.services.get(keys.body_double)
    session, _, _ = await bd.start(member, mode="guided", task=board.get(made.id))
    await wall.run_jobs()  # the step pictures (the scripted model's PNG)
    return session.id


async def test_the_steps_picture_shows_through_the_walls_own_route(wall: Scenario) -> None:
    from tests.fakes.scripted_provider import TINY_PNG

    husband, erin = wall.member("Husband"), wall.member("Erin")
    session_id = await guided_kitchen(wall)
    live = (await get(wall, f"/wall/focus/live?member={husband.id}")).text
    found = re.search(r'<img src="(/wall/focus/picture/[^"]+)"', live)
    assert found is not None and f"member={husband.id}" in found[1]
    got = await get(wall, found[1].replace("&amp;", "&"))
    assert got.status_code == 200 and got.content == TINY_PNG
    theirs = await get(wall, f"/wall/focus/picture/{session_id}/0?member={erin.id}")
    assert theirs.status_code == 404  # only for the session's own person
    assert (await get(wall, f"/wall/focus/picture/{session_id}/0")).status_code == 404


async def test_the_running_sheet_has_the_loop_and_the_wall_its_player(wall: Scenario) -> None:
    husband = wall.member("Husband")
    await post(wall, "/wall/focus/start", member=str(husband.id), what="typed",
               typed="the dishes", mode="silent", minutes="0")  # fmt: skip
    sheet = (await get(wall, f"/wall/focus?member={husband.id}")).text
    assert "data-focus-music" in sheet and "data-music-play" in sheet
    assert re.search(r'<option value="[a-z]+" data-src="[^"]+\.(?:mp3|ogg|m4a|opus)', sheet)
    # the player is the wall's, outside the sheet, so a redraw doesn't stop it
    assert '<audio id="wall-music"' in await screen(wall)
    assert "<audio" not in sheet


async def test_the_walls_loop_choice_is_kept_and_noted_once_it_plays(wall: Scenario) -> None:
    from themi_home.body_double import BodyDoublePreferences

    husband = wall.member("Husband")
    await post(wall, "/wall/focus/start", member=str(husband.id), what="typed",
               typed="the dishes", mode="silent", minutes="0")  # fmt: skip
    kept = await post(wall, "/wall/focus/music", member=str(husband.id), sound="rain",
                      volume="30", played="1")  # fmt: skip
    assert kept.status_code == 204
    prefs = wall.app.store.preferences(husband.id, BodyDoublePreferences)
    assert prefs.body_double_sound == "rain" and prefs.body_double_volume == 30
    (row,) = session_rows(wall)
    assert row["music"] == "builtin:rain"
    bad = await post(wall, "/wall/focus/music", member=str(husband.id), volume="loud")
    assert bad.status_code == 400
    assert (await post(wall, "/wall/focus/music", member="999")).status_code == 404
