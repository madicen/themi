"""`make dev`: the Telegram simulator and the dev runner."""

from __future__ import annotations

import asyncio
import stat
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.telegram_api import BOT_TOKEN
from tests.fixtures.family import ERIN_TELEGRAM_ID
from tests.integration.test_runtime import wait_for
from themi import clock
from themi.accounts import AccountStore
from themi.ai.settings import AISettingsStore
from themi.cli import build_runtime
from themi.core.agent import SETUP_NEEDED_TEXT
from themi.storage import open_database
from tools.dev import runner
from tools.dev.simulator import NEWCOMER_ID, Simulator


@pytest.fixture
def simulator() -> Iterator[Simulator]:
    sim = Simulator()
    sim.start()
    yield sim
    sim.stop()


def bot_call(sim: Simulator, method: str, **params: Any) -> Any:
    """Call the simulator's Bot API the way Themi would."""
    response = httpx.post(f"{sim.base_url}{BOT_TOKEN}/{method}", json=params)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def state(sim: Simulator, chat: int) -> dict[str, Any]:
    return httpx.get(f"{sim.url}/sim/state", params={"chat": chat}).json()


def test_the_page_is_served(simulator: Simulator) -> None:
    page = httpx.get(simulator.url + "/")
    assert page.status_code == 200 and "<title>Themi simulator</title>" in page.text


def test_typed_messages_become_updates_and_show_in_the_transcript(simulator: Simulator) -> None:
    httpx.post(f"{simulator.url}/sim/send", json={"user_id": ERIN_TELEGRAM_ID, "text": " hi "})
    updates = bot_call(simulator, "getUpdates")
    assert [u["message"]["text"] for u in updates] == ["hi"]
    assert updates[0]["message"]["from"]["id"] == ERIN_TELEGRAM_ID

    entries = state(simulator, ERIN_TELEGRAM_ID)["entries"]
    assert [(e["sender"], e["text"]) for e in entries] == [("person", "hi")]
    assert state(simulator, NEWCOMER_ID)["entries"] == []

    empty = httpx.post(f"{simulator.url}/sim/send", json={"user_id": 1001, "text": "  "})
    assert empty.status_code == 400


def test_the_bots_sends_edits_reactions_and_typing_show_up(simulator: Simulator) -> None:
    simulator.send_text(ERIN_TELEGRAM_ID, "remind me about the vet")
    person_message = simulator.transcript(ERIN_TELEGRAM_ID)[0].message_id

    bot_call(simulator, "sendChatAction", chat_id=ERIN_TELEGRAM_ID, action="typing")
    assert state(simulator, ERIN_TELEGRAM_ID)["typing"] is True
    keyboard = {"inline_keyboard": [[{"text": "Yes", "callback_data": "t1"}]]}
    sent = bot_call(
        simulator, "sendMessage", chat_id=ERIN_TELEGRAM_ID, text="Add it?", reply_markup=keyboard
    )
    assert state(simulator, ERIN_TELEGRAM_ID)["typing"] is False
    bot_call(simulator, "setMessageReaction", chat_id=ERIN_TELEGRAM_ID,
             message_id=person_message, reaction=[{"type": "emoji", "emoji": "👍"}])  # fmt: skip

    entries = state(simulator, ERIN_TELEGRAM_ID)["entries"]
    assert entries[0]["bot_reactions"] == ["👍"]
    assert entries[1]["buttons"] == [{"text": "Yes", "data": "t1"}]
    assert state(simulator, ERIN_TELEGRAM_ID)["latest"][str(ERIN_TELEGRAM_ID)] == entries[1]["seq"]

    bot_call(
        simulator,
        "editMessageText",
        chat_id=ERIN_TELEGRAM_ID,
        message_id=sent["message_id"],
        text="Added.",
    )
    edited = state(simulator, ERIN_TELEGRAM_ID)["entries"][1]
    assert (edited["text"], edited["buttons"], edited["edited"]) == ("Added.", [], True)


def test_taps_and_reactions_become_updates(simulator: Simulator) -> None:
    sent = bot_call(simulator, "sendMessage", chat_id=ERIN_TELEGRAM_ID, text="Washer's done.")
    message_id = sent["message_id"]
    body = {"user_id": ERIN_TELEGRAM_ID, "message_id": message_id}

    httpx.post(f"{simulator.url}/sim/tap", json={**body, "data": "t1"})
    httpx.post(f"{simulator.url}/sim/react", json={**body, "emoji": "✅"})
    assert state(simulator, ERIN_TELEGRAM_ID)["entries"][0]["reactions"] == ["✅"]
    httpx.post(f"{simulator.url}/sim/react", json={**body, "emoji": "✅"})  # again: removed
    assert state(simulator, ERIN_TELEGRAM_ID)["entries"][0]["reactions"] == []

    updates = bot_call(simulator, "getUpdates")
    assert updates[0]["callback_query"]["data"] == "t1"
    assert [r["emoji"] for r in updates[1]["message_reaction"]["new_reaction"]] == ["✅"]
    assert updates[2]["message_reaction"]["new_reaction"] == []

    query = updates[0]["callback_query"]["id"]
    bot_call(simulator, "answerCallbackQuery", callback_query_id=query, text="Got it")
    notice = state(simulator, ERIN_TELEGRAM_ID)["entries"][-1]
    assert (notice["sender"], notice["text"]) == ("notice", "Got it")


def test_skipping_moves_themis_clock_ahead(simulator: Simulator) -> None:
    before = clock.now()
    response = httpx.post(f"{simulator.url}/sim/skip", json={"minutes": 90})
    assert response.status_code == 200
    assert clock.shifted_by() == timedelta(minutes=90)
    assert clock.now() - before >= timedelta(minutes=90)
    assert state(simulator, ERIN_TELEGRAM_ID)["skipped_minutes"] == 90

    too_far = httpx.post(f"{simulator.url}/sim/skip", json={"minutes": 0})
    assert too_far.status_code == 400 and clock.shifted_by() == timedelta(minutes=90)


def test_the_website_link_signs_in_as_the_chosen_person(simulator: Simulator) -> None:
    missing = httpx.get(f"{simulator.url}/sim/website", params={"person": ERIN_TELEGRAM_ID})
    assert missing.status_code == 404  # no runner attached
    simulator.login = lambda person: f"http://site/login/{person}" if person < 1003 else None
    link = httpx.get(f"{simulator.url}/sim/website", params={"person": ERIN_TELEGRAM_ID})
    assert (link.status_code, link.headers["location"]) == (303, "http://site/login/1001")
    newcomer = httpx.get(f"{simulator.url}/sim/website", params={"person": NEWCOMER_ID})
    assert newcomer.status_code == 404


def test_dev_settings_keep_their_own_key_and_database(tmp_path: Path) -> None:
    settings = runner.dev_settings(tmp_path / "dev", "http://127.0.0.1:9", {})
    key_file = tmp_path / "dev" / "secret.key"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert settings.db_path == tmp_path / "dev" / "themi.db"
    assert settings.telegram_api_url == "http://127.0.0.1:9"
    again = runner.dev_settings(tmp_path / "dev", "http://127.0.0.1:9", {"THEMI_HTTP_PORT": "0"})
    assert again.secret_key.reveal() == settings.secret_key.reveal()
    assert again.http_port == 0


def test_seeding_happens_once_and_sets_the_gemini_key(tmp_path: Path) -> None:
    settings = runner.dev_settings(tmp_path, "http://127.0.0.1:9", {})
    with pytest.raises(SystemExit, match="make dev first"):
        runner.invite(settings, "Sam")

    assert runner.seed(settings, "AIza-test-key") == runner.SeedResult(seeded=True, key_set=True)
    assert runner.seed(settings, "") == runner.SeedResult(seeded=False, key_set=True)

    assert (runner.login_link(settings) or "").startswith("http://127.0.0.1:8080/login/")
    assert runner.login_link(settings, NEWCOMER_ID) is None
    assert runner.invite(settings, "Sam")

    store = AccountStore(open_database(settings.db_path), settings.cipher())
    ai = AISettingsStore(store.db, settings.cipher())
    members = store.list_members()
    assert [(m.name, m.telegram_user_id) for m in members] == [
        ("Erin", 1001),
        ("Husband", 1002),
        ("Sam", None),
    ]
    assert all(b.has_key for m in members[:2] for b in ai.backends(m.id))
    store.db.close()


def test_the_banner_says_when_there_is_no_ai_key(tmp_path: Path) -> None:
    with_key = runner._banner(
        "http://127.0.0.1:8090", "link", runner.SeedResult(True, True), tmp_path
    )
    assert "http://localhost:8090" in with_key and "Seeded Erin and Husband" in with_key
    assert "No AI key" not in with_key
    without = runner._banner("u", "link", runner.SeedResult(False, False), tmp_path)
    assert "No AI key" in without and "Seeded" not in without


async def test_a_message_from_the_simulator_gets_a_reply(
    simulator: Simulator, tmp_path: Path
) -> None:
    settings = runner.dev_settings(tmp_path, simulator.url, {"THEMI_HTTP_PORT": "0"})
    runner.seed(settings, "")  # no key: Themi answers that setup is needed, with no network
    runtime = build_runtime(settings, scheduler_tick=timedelta(milliseconds=50))
    task = asyncio.create_task(runtime.run())
    try:
        simulator.send_text(ERIN_TELEGRAM_ID, "hello")
        await wait_for(
            lambda: (
                [e.text for e in simulator.transcript(ERIN_TELEGRAM_ID)][1:] == [SETUP_NEEDED_TEXT]
            ),
            timeout=10,
        )
    finally:
        runtime.stop()
        await asyncio.wait_for(task, timeout=10)
