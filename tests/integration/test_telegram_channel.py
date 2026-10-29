"""The Telegram channel against a local fake of the Bot API, over real HTTP."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import pytest

from tests.fakes.telegram_api import BOT_TOKEN, FakeTelegram
from tests.fixtures.family import ERIN_TELEGRAM_ID, HUSBAND_TELEGRAM_ID, SeededFamily
from themi.accounts import SYSTEM
from themi.channels.events import Button, EchoHandler, InboundEvent
from themi.channels.outbox import Outbox
from themi.channels.pda import PdaShield
from themi.channels.telegram import (
    ALREADY_HANDLED_TEXT,
    NOT_YOURS_TEXT,
    TelegramChannel,
)
from themi.storage.secrets import Secret

GUEST_TELEGRAM_ID = 3001


class Recorder:
    """Collects events; optionally fails or stops the loop when one arrives."""

    def __init__(self) -> None:
        self.events: list[InboundEvent] = []
        self.fail_on: str | None = None
        self.stop: asyncio.Event | None = None

    async def handle(self, event: InboundEvent, channel: TelegramChannel) -> None:
        self.events.append(event)
        if self.stop is not None:
            self.stop.set()
        if self.fail_on and event.text == self.fail_on:
            raise RuntimeError("handler blew up")


class NoSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        await asyncio.sleep(0)


def make_channel(family: SeededFamily, fake: FakeTelegram, handler, sleep=None) -> TelegramChannel:
    return TelegramChannel.from_token(
        Secret(BOT_TOKEN),
        family.store,
        handler,
        base_url=fake.base_url,
        base_file_url=fake.base_file_url,
        poll_timeout=0,
        sleep=sleep or NoSleep(),
    )


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
async def channel(
    family: SeededFamily, fake_telegram: FakeTelegram, recorder: Recorder
) -> AsyncIterator[TelegramChannel]:
    ch = make_channel(family, fake_telegram, recorder)
    await ch.start()
    yield ch
    await ch.stop()


# ----- pairing and who may talk -----------------------------------------------


async def test_start_deletes_any_webhook(channel: TelegramChannel, fake_telegram: FakeTelegram):
    assert fake_telegram.calls("deleteWebhook") == [{"drop_pending_updates": False}]


async def test_invite_code_pairs_a_new_member(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram
) -> None:
    guest = family.store.create_member(SYSTEM, "Guest")
    code = family.store.create_invite(SYSTEM, guest.id)
    fake_telegram.send_text(GUEST_TELEGRAM_ID, f"/start {code}")
    assert await channel.poll_once() == 1
    assert family.store.get_member(guest.id).telegram_user_id == GUEST_TELEGRAM_ID
    assert fake_telegram.sent_texts(GUEST_TELEGRAM_ID) == [
        "Hi Guest! This chat is now connected to Themi."
    ]


async def test_paired_member_sending_start_again(
    channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "/start")
    await channel.poll_once()
    assert "already connected" in fake_telegram.sent_texts(ERIN_TELEGRAM_ID)[0]
    assert recorder.events == []


async def test_bad_codes_are_rate_limited(
    channel: TelegramChannel, fake_telegram: FakeTelegram
) -> None:
    for _ in range(7):
        fake_telegram.send_text(GUEST_TELEGRAM_ID, "/start AAAA-BBBB")
    await channel.poll_once()
    replies = fake_telegram.sent_texts(GUEST_TELEGRAM_ID)
    assert len(replies) == 5  # the 6th and 7th attempts get no answer at all
    assert all("didn't work" in r for r in replies)


async def test_strangers_are_ignored_and_their_words_never_logged(
    channel: TelegramChannel,
    fake_telegram: FakeTelegram,
    recorder: Recorder,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    fake_telegram.send_text(9999, "here is my secret plan")
    await channel.poll_once()
    assert recorder.events == []
    assert fake_telegram.sent_texts(9999) == []
    assert "9999" in caplog.text
    assert "secret plan" not in caplog.text


async def test_group_chats_are_ignored_for_now(
    channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "hi all", chat_id=-100, chat_type="group")
    await channel.poll_once()
    assert recorder.events == []


# ----- inbound events ---------------------------------------------------------


async def test_text_becomes_an_event_and_is_logged(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "used the last olive oil")
    await channel.poll_once()
    (event,) = recorder.events
    assert (event.kind, event.text, event.member.id) == (
        "text",
        "used the last olive oil",
        family.erin.id,
    )
    assert event.chat_id == ERIN_TELEGRAM_ID and event.message_id is not None
    (logged,) = family.store.recent_messages(family.erin.id)
    assert (logged.direction, logged.text, logged.telegram_message_id) == (
        "in",
        "used the last olive oil",
        event.message_id,
    )


async def test_a_reply_carries_the_message_it_replies_to(
    channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "/bug this was wrong", reply_to=321)
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "plain message")
    await channel.poll_once()
    replying, plain = recorder.events
    assert replying.reply_to_message_id == 321
    assert plain.reply_to_message_id is None


async def test_voice_note_is_downloaded(
    channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    fake_telegram.send_voice(ERIN_TELEGRAM_ID, b"OggS-fake-voice-bytes", duration=7)
    await channel.poll_once()
    (event,) = recorder.events
    assert event.kind == "voice" and event.voice is not None
    assert event.voice.data == b"OggS-fake-voice-bytes"
    assert (event.voice.mime_type, event.voice.duration_seconds) == ("audio/ogg", 7)


async def test_buttons_carry_server_side_payloads(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    message_id = await channel.send_text(
        family.erin,
        "Washer's done whenever you're free.",
        [
            Button("Dryer now", "laundry", {"cycle": 12}),
            Button("Later tonight", "laundry", {"cycle": 12, "later": True}),
        ],
    )
    keyboard = fake_telegram.last_keyboard(ERIN_TELEGRAM_ID)
    assert [b["text"] for b in keyboard] == ["Dryer now", "Later tonight"]
    assert all("cycle" not in b["callback_data"] for b in keyboard)  # opaque tokens only

    fake_telegram.tap(ERIN_TELEGRAM_ID, keyboard[1]["callback_data"], message_id)
    await channel.poll_once()
    (event,) = recorder.events
    assert event.kind == "button" and event.button is not None
    assert (event.button.label, event.button.kind) == ("Later tonight", "laundry")
    assert event.button.payload == {"cycle": 12, "later": True}
    assert event.button.message_id == message_id
    assert fake_telegram.calls("answerCallbackQuery")[-1].get("text") is None


async def test_a_keyboard_answers_only_once(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    message_id = await channel.send_text(
        family.erin, "Go ahead?", [Button("Go ahead", "approval"), Button("Not now", "approval")]
    )
    first, second = (b["callback_data"] for b in fake_telegram.last_keyboard(ERIN_TELEGRAM_ID))
    fake_telegram.tap(ERIN_TELEGRAM_ID, first, message_id)
    fake_telegram.tap(ERIN_TELEGRAM_ID, second, message_id)
    await channel.poll_once()
    assert len(recorder.events) == 1
    assert fake_telegram.calls("answerCallbackQuery")[-1]["text"] == ALREADY_HANDLED_TEXT


async def test_someone_elses_button_is_refused(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    message_id = await channel.send_text(family.erin, "Go ahead?", [Button("Go ahead", "approval")])
    (button,) = fake_telegram.last_keyboard(ERIN_TELEGRAM_ID)
    fake_telegram.tap(HUSBAND_TELEGRAM_ID, button["callback_data"], message_id)
    await channel.poll_once()
    assert recorder.events == []
    assert fake_telegram.calls("answerCallbackQuery")[-1]["text"] == NOT_YOURS_TEXT
    # ...and it still works for Erin.
    fake_telegram.tap(ERIN_TELEGRAM_ID, button["callback_data"], message_id)
    await channel.poll_once()
    assert len(recorder.events) == 1


async def test_reactions_report_only_new_emoji(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    message_id = await channel.send_text(family.erin, "Stage the Safeway cart?")
    fake_telegram.react(ERIN_TELEGRAM_ID, message_id, new=["✅"])
    fake_telegram.react(ERIN_TELEGRAM_ID, message_id, new=["✅"], old=["✅"])  # no change
    fake_telegram.react(ERIN_TELEGRAM_ID, message_id, new=[], old=["✅"])  # removed
    await channel.poll_once()
    (event,) = recorder.events
    assert event.kind == "reaction" and event.reaction is not None
    assert event.reaction.added == ("✅",) and event.reaction.message_id == message_id


async def test_polling_asks_for_reaction_updates(
    channel: TelegramChannel, fake_telegram: FakeTelegram
) -> None:
    await channel.poll_once()
    params = fake_telegram.calls("getUpdates")[-1]
    assert set(params["allowed_updates"]) == {"message", "callback_query", "message_reaction"}


# ----- outbound ---------------------------------------------------------------


async def test_outbound_messages_are_logged_with_their_ids(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram
) -> None:
    message_id = await channel.send_text(family.husband, "Feeders are getting low.")
    await channel.edit_text(family.husband, message_id, "Feeders are topped up. Thanks!")
    await channel.react(family.husband, message_id, "👍")
    logged = family.store.recent_messages(family.husband.id)
    assert [(m.direction, m.text, m.telegram_message_id) for m in logged] == [
        ("out", "Feeders are getting low.", message_id),
        ("out", "Feeders are topped up. Thanks!", message_id),
    ]
    (edit,) = fake_telegram.calls("editMessageText")
    assert int(edit["message_id"]) == message_id
    (reaction,) = fake_telegram.calls("setMessageReaction")
    assert reaction["reaction"] == [{"type": "emoji", "emoji": "👍"}]


async def test_typing_indicator_runs_while_working(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram
) -> None:
    async with channel.typing(family.erin):
        await asyncio.sleep(0.05)
    actions = fake_telegram.calls("sendChatAction")
    assert actions and actions[0]["action"] == "typing"


async def test_sending_retries_after_flood_control(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram
) -> None:
    fake_telegram.fail("sendMessage", 429, "Too Many Requests", retry_after=3)
    await channel.send_text(family.erin, "hello again")
    assert fake_telegram.sent_texts(ERIN_TELEGRAM_ID)[-1] == "hello again"
    assert 3.0 in channel._sleep.waits  # type: ignore[attr-defined]


async def test_unpaired_members_cannot_be_messaged(
    family: SeededFamily, channel: TelegramChannel
) -> None:
    guest = family.store.create_member(SYSTEM, "Guest")
    with pytest.raises(ValueError, match="hasn't paired"):
        await channel.send_text(guest, "hi")


# ----- resilience -------------------------------------------------------------


async def test_handler_failures_dont_block_later_updates(
    channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    recorder.fail_on = "boom"
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "boom")
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "after")
    await channel.poll_once()
    assert [e.text for e in recorder.events] == ["boom", "after"]
    await channel.poll_once()
    assert len(recorder.events) == 2  # the failed one isn't retried forever


async def test_restart_does_not_reprocess_updates(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "first")
    await channel.poll_once()
    await channel.stop()

    restarted_recorder = Recorder()
    restarted = make_channel(family, fake_telegram, restarted_recorder)
    await restarted.start()
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "second")
    await restarted.poll_once()
    await restarted.stop()
    assert [e.text for e in recorder.events] == ["first"]
    assert [e.text for e in restarted_recorder.events] == ["second"]
    await channel.start()  # so the fixture's teardown can stop it cleanly


async def test_run_recovers_from_polling_errors(
    family: SeededFamily, fake_telegram: FakeTelegram, recorder: Recorder
) -> None:
    sleep = NoSleep()
    ch = make_channel(family, fake_telegram, recorder, sleep)
    await ch.start()
    fake_telegram.fail("getUpdates", 502, "Bad Gateway", times=2)
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "still there?")
    recorder.stop = asyncio.Event()
    await asyncio.wait_for(ch.run(recorder.stop), timeout=5)
    await ch.stop()
    assert [e.text for e in recorder.events] == ["still there?"]
    assert len(sleep.waits) == 2  # backed off twice, then carried on


async def test_echo_handler_round_trip(family: SeededFamily, fake_telegram: FakeTelegram) -> None:
    ch = make_channel(family, fake_telegram, None)
    ch.handler = EchoHandler(Outbox(family.store, ch, PdaShield(None)))
    await ch.start()
    fake_telegram.send_text(ERIN_TELEGRAM_ID, "hello")
    await ch.poll_once()
    await ch.stop()
    assert fake_telegram.sent_texts(ERIN_TELEGRAM_ID) == ["You said: hello"]


async def test_more_than_two_buttons_go_on_rows(
    family: SeededFamily, channel: TelegramChannel, fake_telegram: FakeTelegram
) -> None:
    # Erin's idea #80: two a row for longer labels, three for short ones.
    await channel.send_text(
        family.erin,
        "Paper towels: which list?",
        [Button(label, "x") for label in ("Grocery list", "Things to Buy", "Costco", "Not now")],
    )
    (call,) = fake_telegram.calls("sendMessage")
    rows = call["reply_markup"]["inline_keyboard"]
    assert [[b["text"] for b in row] for row in rows] == [
        ["Grocery list", "Things to Buy"],
        ["Costco", "Not now"],
    ]
