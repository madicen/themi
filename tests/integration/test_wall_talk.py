"""F59g (Michael's idea #257): talk to Themi from the wall, typed or said. The frame is
shared, so it asks who's talking first; the line goes in as that person's own message, and
the answer shows in the sheet and in Telegram. The scenario starts Wednesday 21 October 2026,
9 am, Los Angeles."""

from __future__ import annotations

import re
from datetime import timedelta

from tests.fixtures.web import web_client
from tests.integration.test_wall_list_views import csrf, get, post
from tests.integration.test_wall_screen import frame, wall, words
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["wall"]  # the fixture


async def test_the_sheet_asks_whos_talking_first(wall: Scenario) -> None:
    page = (await get(wall, "/wall")).text
    assert 'hx-get="/wall/talk"' in page and "Talk to Themi" in page
    sheet = words((await get(wall, "/wall/talk")).text)
    assert "Who&#39;s this?" in sheet
    assert "Erin" in sheet and "Husband" in sheet


async def test_a_typed_line_is_their_message_and_the_answer_shows(wall: Scenario) -> None:
    husband = wall.member("Husband")
    wall.primary.queue_text("Oat milk's on the grocery list.")
    sheet = (await post(wall, "/wall/talk", member=str(husband.id),
                        text="add oat milk to groceries")).text  # fmt: skip
    turn = wall.primary.requests[-1].messages[0].text
    assert turn.endswith("Husband says:\nadd oat milk to groceries")  # as their own message
    assert "add oat milk to groceries" in sheet  # what they said, in the sheet
    sent = wall.app.db.query("SELECT text FROM outbox WHERE member_id = ?", (husband.id,))
    assert [r["text"] for r in sent] == ["Oat milk's on the grocery list."]  # to Telegram
    await wall.app.outbox.flush()
    lines = (await get(wall, f"/wall/talk/lines?member={husband.id}")).text
    assert "Oat milk&#39;s on the grocery list." in lines


async def test_who_is_kept_for_five_minutes_on_that_frame(wall: Scenario) -> None:
    husband = wall.member("Husband")
    async with web_client(wall) as client:
        await frame(wall, client)
        headers = {"HX-Request": "true"}
        chosen = (await client.get(f"/wall/talk?member={husband.id}", headers=headers)).text
        assert "Hi, Husband" in chosen
        assert "Hi, Husband" in (await client.get("/wall/talk", headers=headers)).text
        clock.advance(timedelta(minutes=6))
        assert "Who&#39;s this?" in (await client.get("/wall/talk", headers=headers)).text
        await client.get(f"/wall/talk?member={husband.id}", headers=headers)
        again = (await client.get("/wall/talk?member=0", headers=headers)).text
        assert "Who&#39;s this?" in again  # "Not Husband?"


async def test_no_one_chosen_or_a_stranger_is_refused(wall: Scenario) -> None:
    assert (await post(wall, "/wall/talk", text="hello")).status_code == 400
    assert (await post(wall, "/wall/talk", member="999", text="hello")).status_code == 404
    async with web_client(wall) as client:  # no frame: back to pairing
        response = await client.post("/wall/talk", data={"member": "1", "text": "hello"})
        assert response.status_code == 401


async def test_a_said_line_is_transcribed_and_answered(wall: Scenario) -> None:
    husband = wall.member("Husband")
    wall.primary.queue_transcription("what's on the grocery list")
    wall.primary.queue_text("Nothing on it right now.")
    async with web_client(wall) as client:
        await frame(wall, client)
        token = await csrf(client)
        sheet = (
            await client.post(
                "/wall/say",
                data={"member": str(husband.id)},
                files={"audio": ("clip.webm", b"\x1aE\xdf\xa3 fake", "audio/webm;codecs=opus")},
                headers={"X-CSRF-Token": token, "HX-Request": "true"},
            )
        ).text
    assert "what&#39;s on the grocery list" in sheet  # what was heard
    transcribe = wall.primary.requests[0]
    assert transcribe.op == "transcribe" and transcribe.audio.endswith(b" fake")
    sent = wall.app.db.query("SELECT text FROM outbox WHERE member_id = ?", (husband.id,))
    assert "Nothing on it right now." in [r["text"] for r in sent]


async def test_the_mic_is_hidden_until_the_frame_says_it_can_record(wall: Scenario) -> None:
    husband = wall.member("Husband")
    sheet = (await get(wall, f"/wall/talk?member={husband.id}")).text
    assert re.search(r"<button[^>]*data-talk-mic[^>]*hidden>", sheet)
    script = re.search(r'src="([^"]*wall\.js[^"]*)"', (await get(wall, "/wall")).text)
    assert script is not None
    js = (await get(wall, script[1])).text
    assert "getUserMedia" in js and "MediaRecorder" in js
