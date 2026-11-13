"""SL1-SL4: the Slack channel against a local fake of Slack, over real HTTP (and, for the
socket, a real WebSocket)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from tests.fakes.slack_api import APP_TOKEN, BOT_TOKEN, MICHAEL, STRANGER, FakeSlack
from tests.fixtures.family import SeededFamily
from themi.accounts import SYSTEM, Member
from themi.channels.buttons import ALREADY_HANDLED_TEXT, NOT_YOURS_TEXT
from themi.channels.events import InboundEvent
from themi.channels.slack import (
    BAD_CODE_TEXT,
    NAME,
    NOT_PAIRED_TEXT,
    SlackChannel,
)
from themi.channels.slack_api import SlackError
from themi.standard.slack import SlackModule
from themi.storage import migrations
from themi.storage.secrets import Secret


class NoSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        await asyncio.sleep(0)


def make_channel(family: SeededFamily, fake: FakeSlack, sleep: NoSleep | None = None,
                 **kwargs: object) -> SlackChannel:  # fmt: skip
    assert SlackModule.migrations is not None
    migrations.apply_track(family.db, "slack", SlackModule.migrations)
    return SlackChannel.from_tokens(
        family.store, Secret(BOT_TOKEN), Secret(APP_TOKEN), base_url=fake.base_url,
        sleep=sleep or NoSleep(), **kwargs,  # type: ignore[arg-type]
    )  # fmt: skip


def on_slack(family: SeededFamily, member: Member, user: str = MICHAEL) -> Member:
    family.store.set_identity(member.id, NAME, user)
    return family.store.get_member(member.id)


# ----- SL1: sending ---------------------------------------------------------------------


async def test_a_message_goes_to_their_dm_with_an_integer_id(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel = make_channel(family, fake_slack)
    await channel.start()
    assert channel.bot_user_id == "UTHEMI"
    erin = on_slack(family, family.erin)
    first = await channel.send_text(erin, "Tea & <biscuits> at 3?")
    second = await channel.send_text(erin, "And another", link_preview=False)
    assert isinstance(first, int) and second != first
    assert len(fake_slack.calls("conversations.open")) == 1  # opened once, then remembered
    assert fake_slack.texts(MICHAEL) == ["Tea & <biscuits> at 3?", "And another"]
    raw = fake_slack.posts(MICHAEL)
    assert raw[0]["text"] == "Tea &amp; &lt;biscuits&gt; at 3?"
    assert raw[1]["unfurl_links"] == "false" and "unfurl_links" not in raw[0]
    channel_id, ts = channel.where(first) or ("", "")
    assert channel_id == "DMICHAEL" and ts
    assert channel.message_id(channel_id, ts) == first
    logged = family.db.query(
        "SELECT text, telegram_message_id FROM message_log WHERE member_id = ? ORDER BY id",
        (erin.id,),
    )
    assert [(r["text"], r["telegram_message_id"]) for r in logged] == [
        ("Tea & <biscuits> at 3?", first),
        ("And another", second),
    ]
    await channel.stop()


async def test_someone_not_on_slack_cant_be_written_to(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel = make_channel(family, fake_slack)
    with pytest.raises(ValueError, match="hasn't paired with Slack"):
        await channel.send_text(family.erin, "hello")


async def test_an_edit_changes_the_message_where_it_is(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel = make_channel(family, fake_slack)
    erin = on_slack(family, family.erin)
    sent = await channel.send_text(erin, "Before")
    await channel.edit_text(erin, sent, "After")
    update = fake_slack.calls("chat.update")[-1]
    assert (update["channel"], update["ts"]) == channel.where(sent)
    assert update["text"] == "After"


async def test_a_rate_limit_waits_as_slack_asks(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    sleep = NoSleep()
    channel = make_channel(family, fake_slack, sleep)
    erin = on_slack(family, family.erin)
    fake_slack.fail("chat.postMessage", "ratelimited", status=429, retry_after=3)
    await channel.send_text(erin, "hello")
    assert sleep.waits == [3.0]
    assert fake_slack.texts(MICHAEL) == ["hello"]


async def test_slack_saying_no_is_an_error(family: SeededFamily, fake_slack: FakeSlack) -> None:
    channel = make_channel(family, fake_slack)
    erin = on_slack(family, family.erin)
    fake_slack.fail("chat.postMessage", "channel_not_found")
    with pytest.raises(SlackError) as caught:
        await channel.send_text(erin, "hello")
    assert caught.value.error == "channel_not_found"


async def test_the_test_button_says_which_token_failed(fake_slack: FakeSlack) -> None:
    def module(bot: str, app: str) -> SlackModule:
        return SlackModule(Secret(bot), Secret(app), base_url=fake_slack.base_url)

    assert await module(BOT_TOKEN, APP_TOKEN).check() is None
    bad_bot = await module("xoxb-wrong", APP_TOKEN).check()
    assert bad_bot is not None and "bot token" in bad_bot and "app-level" not in bad_bot
    bad_app = await module(BOT_TOKEN, "xapp-wrong").check()
    assert bad_app is not None and "app-level token" in bad_app and "bot token" not in bad_app
    missing = await SlackModule(Secret(BOT_TOKEN), None).check()
    assert missing is not None and "both tokens" in missing


# ----- SL2: receiving and pairing ---------------------------------------------------------


class Recorder:
    """Collects events; optionally stops the socket loop when one arrives."""

    def __init__(self) -> None:
        self.events: list[InboundEvent] = []
        self.stop: asyncio.Event | None = None
        self.after = 1

    async def handle(self, event: InboundEvent, channel: Any) -> None:
        self.events.append(event)
        if self.stop is not None and len(self.events) >= self.after:
            self.stop.set()


def listening(
    family: SeededFamily, fake: FakeSlack, **kwargs: Any
) -> tuple[SlackChannel, Recorder]:
    channel = make_channel(family, fake, **kwargs)
    recorder = Recorder()
    channel.handler = recorder
    channel.bot_user_id = "UTHEMI"
    return channel, recorder


async def test_a_dm_from_a_member_reaches_the_agent(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel, recorder = listening(family, fake_slack)
    erin = on_slack(family, family.erin)
    envelope = fake_slack.dm(
        MICHAEL, "Move standup to <https://cal.test/x|the calendar> &amp; tell <@U42|Priya>"
    )
    await channel.dispatch(envelope)
    [event] = recorder.events
    assert event.kind == "text" and event.member.id == erin.id
    assert event.text == "Move standup to https://cal.test/x & tell Priya"
    ts = envelope["payload"]["event"]["ts"]
    assert event.message_id == channel.message_id("DMICHAEL", ts)
    assert (
        family.db.scalar(
            "SELECT text FROM message_log WHERE member_id = ? AND direction = 'in'", (erin.id,)
        )
        == event.text
    )


async def test_a_repeated_event_is_dropped(family: SeededFamily, fake_slack: FakeSlack) -> None:
    channel, recorder = listening(family, fake_slack)
    on_slack(family, family.erin)
    envelope = fake_slack.dm(MICHAEL, "once")
    await channel.dispatch(envelope)
    await channel.dispatch(envelope)  # Slack's retry: the same event id
    assert [e.text for e in recorder.events] == ["once"]


async def test_bots_edits_and_other_conversations_are_ignored(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel, recorder = listening(family, fake_slack)
    on_slack(family, family.erin)
    await channel.dispatch(fake_slack.dm(MICHAEL, "edited", subtype="message_changed"))
    from_bot = fake_slack.dm(MICHAEL, "echo")
    from_bot["payload"]["event"]["bot_id"] = "BTHEMI"
    await channel.dispatch(from_bot)
    in_channel = fake_slack.dm(MICHAEL, "in a channel")
    in_channel["payload"]["event"]["channel_type"] = "channel"
    await channel.dispatch(in_channel)
    assert recorder.events == []


async def test_someone_whose_slack_email_is_a_members_is_paired(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel, recorder = listening(family, fake_slack)
    family.store.set_email(SYSTEM, family.erin.id, "Michael@Work.test")
    await channel.dispatch(fake_slack.dm(MICHAEL, "hello"))
    assert family.store.identity(family.erin.id, NAME) == MICHAEL
    assert fake_slack.texts(MICHAEL) == [
        f"Hi {family.erin.name}! You're connected to Themi here in Slack."
    ]
    assert recorder.events == []  # the hello paired them; it isn't a request
    await channel.dispatch(fake_slack.dm(MICHAEL, "now a request"))
    assert [e.text for e in recorder.events] == ["now a request"]


async def test_email_pairing_can_be_turned_off(family: SeededFamily, fake_slack: FakeSlack) -> None:
    channel, _ = listening(family, fake_slack, pair_by_email=False)
    family.store.set_email(SYSTEM, family.erin.id, "michael@work.test")
    await channel.dispatch(fake_slack.dm(MICHAEL, "hello"))
    assert family.store.identity(family.erin.id, NAME) is None
    assert fake_slack.texts(MICHAEL) == [NOT_PAIRED_TEXT]


async def test_an_invite_code_pairs_and_wrong_codes_are_limited(
    family: SeededFamily, fake_slack: FakeSlack, caplog: pytest.LogCaptureFixture
) -> None:
    from datetime import timedelta

    from themi import clock

    clock.freeze(clock.now())
    channel, _ = listening(family, fake_slack)
    caplog.set_level(logging.INFO)
    for _ in range(5):
        await channel.dispatch(fake_slack.dm(STRANGER, "AAAA-BBBB"))
    assert fake_slack.texts(STRANGER) == [BAD_CODE_TEXT] * 5
    code = family.store.create_invite(SYSTEM, family.husband.id)
    await channel.dispatch(fake_slack.dm(STRANGER, code))  # blocked for the hour
    assert family.store.identity(family.husband.id, NAME) is None
    assert "AAAA-BBBB" not in caplog.text and STRANGER in caplog.text
    clock.advance(timedelta(hours=1, minutes=1))
    await channel.dispatch(fake_slack.dm(STRANGER, code.lower()))
    assert family.store.identity(family.husband.id, NAME) == STRANGER
    assert fake_slack.texts(STRANGER)[-1].startswith(f"Hi {family.husband.name}!")


async def test_a_stranger_hears_how_to_pair_and_what_they_said_isnt_logged(
    family: SeededFamily, fake_slack: FakeSlack, caplog: pytest.LogCaptureFixture
) -> None:
    channel, recorder = listening(family, fake_slack)
    caplog.set_level(logging.DEBUG)
    await channel.dispatch(fake_slack.dm(STRANGER, "what's my salary"))
    assert recorder.events == []
    assert fake_slack.texts(STRANGER) == [NOT_PAIRED_TEXT]
    assert "salary" not in caplog.text


async def test_the_socket_acks_hands_on_and_reconnects(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel, recorder = listening(family, fake_slack)
    on_slack(family, family.erin)
    stop = asyncio.Event()
    recorder.stop, recorder.after = stop, 2
    first = fake_slack.dm(MICHAEL, "over the socket")
    second = fake_slack.dm(MICHAEL, "after a reconnect")
    fake_slack.push(first)
    fake_slack.disconnect()
    fake_slack.push(second)
    await asyncio.wait_for(channel.run(stop), timeout=10)
    assert [e.text for e in recorder.events] == ["over the socket", "after a reconnect"]
    assert {first["envelope_id"], second["envelope_id"]} <= set(fake_slack.acked())
    assert fake_slack.state.connections == 2
    assert channel.last_poll_at is not None


async def test_a_failed_connection_backs_off_and_tries_again(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    sleep = NoSleep()
    channel, recorder = listening(family, fake_slack, sleep=sleep)
    on_slack(family, family.erin)
    stop = asyncio.Event()
    recorder.stop = stop
    fake_slack.fail("apps.connections.open", "internal_error", times=2)
    fake_slack.push(fake_slack.dm(MICHAEL, "got through"))
    await asyncio.wait_for(channel.run(stop), timeout=10)
    assert len(sleep.waits) == 2 and [e.text for e in recorder.events] == ["got through"]


# ----- SL3: buttons, edits and threads ----------------------------------------------------


async def test_a_tap_reaches_the_agent_and_uses_up_the_card(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    from themi.channels.events import Button

    channel, recorder = listening(family, fake_slack)
    erin = on_slack(family, family.erin)
    sent = await channel.send_text(
        erin,
        "Send the report now?",
        [
            Button("Yes", "report", {"id": 7}),
            Button("Later", "report", {"id": 8}),
            Button("Open", "", web_app="https://themi.test/session"),
        ],
    )
    yes, later, link = fake_slack.last_buttons(MICHAEL)
    assert link["url"] == "https://themi.test/session" and "value" not in link
    _, ts = channel.where(sent) or ("", "")
    await channel.dispatch(fake_slack.tap(MICHAEL, yes["value"], ts))
    [event] = recorder.events
    assert event.kind == "button" and event.message_id == sent
    assert event.button is not None
    assert (event.button.label, event.button.kind, event.button.payload) == (
        "Yes",
        "report",
        {"id": 7},
    )
    await channel.dispatch(fake_slack.tap(MICHAEL, later["value"], ts))  # one answer a card
    assert len(recorder.events) == 1
    whisper = fake_slack.calls("chat.postEphemeral")[-1]
    assert (whisper["user"], whisper["text"]) == (MICHAEL, ALREADY_HANDLED_TEXT)


async def test_someone_elses_card_isnt_theirs_to_answer(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    from themi.channels.events import Button

    channel, recorder = listening(family, fake_slack)
    erin = on_slack(family, family.erin)
    on_slack(family, family.husband, STRANGER)
    await channel.send_text(erin, "Yours?", [Button("Yes", "k")])
    [yes] = fake_slack.last_buttons(MICHAEL)
    await channel.dispatch(fake_slack.tap(STRANGER, yes["value"], fake_slack.next_ts()))
    assert recorder.events == []
    assert fake_slack.calls("chat.postEphemeral")[-1]["text"] == NOT_YOURS_TEXT
    await channel.send_text(erin, "Anyone?", [Button("Me", "k")], anyone=True)
    [me] = fake_slack.last_buttons(MICHAEL)
    await channel.dispatch(fake_slack.tap(STRANGER, me["value"], fake_slack.next_ts()))
    assert [e.member.id for e in recorder.events] == [family.husband.id]


async def test_an_edit_with_no_buttons_takes_them_away(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    from themi.channels.events import Button

    channel = make_channel(family, fake_slack)
    erin = on_slack(family, family.erin)
    sent = await channel.send_text(erin, "Pick", [Button("A", "k"), Button("B", "k")])
    await channel.edit_text(erin, sent, "Picked A")
    update = fake_slack.calls("chat.update")[-1]
    assert [b["type"] for b in update["blocks"]] == ["section"]
    await channel.edit_text(erin, sent, "Again?", [Button("Yes", "k")])
    assert fake_slack.buttons(fake_slack.calls("chat.update")[-1])[0]["value"]


async def test_themi_answers_in_the_thread_it_was_asked_in(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    from datetime import timedelta

    from themi import clock

    clock.freeze(clock.now())
    channel, recorder = listening(family, fake_slack)
    erin = on_slack(family, family.erin)
    card = await channel.send_text(erin, "Your day: three meetings")
    _, card_ts = channel.where(card) or ("", "")
    await channel.dispatch(fake_slack.dm(MICHAEL, "move the second one", thread_ts=card_ts))
    [event] = recorder.events
    assert event.reply_to_message_id == card
    assert channel.thread_of(event.message_id or 0) == card_ts
    reply = await channel.send_text(erin, "Moved it to 3.")
    assert fake_slack.posts(MICHAEL)[-1]["thread_ts"] == card_ts
    assert channel.thread_of(reply) == card_ts
    clock.advance(timedelta(minutes=3))  # a nudge later goes to the top of the DM
    await channel.send_text(erin, "A nudge")
    assert "thread_ts" not in fake_slack.posts(MICHAEL)[-1]
    await channel.dispatch(fake_slack.dm(MICHAEL, "again", thread_ts=card_ts))
    await channel.dispatch(fake_slack.dm(MICHAEL, "now at the top"))
    await channel.send_text(erin, "At the top too")
    assert "thread_ts" not in fake_slack.posts(MICHAEL)[-1]


async def test_a_tap_on_a_card_in_a_thread_is_answered_there(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    from themi.channels.events import Button

    channel, recorder = listening(family, fake_slack)
    erin = on_slack(family, family.erin)
    await channel.send_text(erin, "Done?", [Button("Done", "k")])
    [done] = fake_slack.last_buttons(MICHAEL)
    await channel.dispatch(fake_slack.tap(MICHAEL, done["value"], "1.1", thread_ts="1.0"))
    assert len(recorder.events) == 1
    await channel.send_text(erin, "Nice.")
    assert fake_slack.posts(MICHAEL)[-1]["thread_ts"] == "1.0"


# ----- SL4: pictures, voice clips, reactions, /themi --------------------------------------


async def test_pictures_and_a_caption_reach_the_agent(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel, recorder = listening(family, fake_slack)
    on_slack(family, family.erin)
    files = [
        fake_slack.add_file(b"\x89PNG-one", "image/png", "a.png"),
        fake_slack.add_file(b"\xff\xd8-two", "image/jpeg", "b.jpg"),
        fake_slack.add_file(b"x" * 10, "image/png", "huge.png", size=6 * 1024 * 1024),
    ]
    await channel.dispatch(fake_slack.dm(MICHAEL, "what's this?", files=files))
    [event] = recorder.events
    assert event.kind == "picture" and event.text == "what's this?"
    assert [p.data for p in event.pictures] == [b"\x89PNG-one", b"\xff\xd8-two"]
    assert [p.mime_type for p in event.pictures] == ["image/png", "image/jpeg"]
    logged = family.db.query("SELECT text FROM message_log WHERE direction = 'in' ORDER BY id")
    assert [r["text"] for r in logged] == ["[a picture] what's this?", "[a picture]"]


async def test_a_voice_clip_reaches_the_agent(family: SeededFamily, fake_slack: FakeSlack) -> None:
    channel, recorder = listening(family, fake_slack)
    on_slack(family, family.erin)
    clip = fake_slack.add_file(b"audio-bytes", "audio/webm", "clip.webm",
                               subtype="slack_audio", duration_ms=4200)  # fmt: skip
    await channel.dispatch(fake_slack.dm(MICHAEL, "", files=[clip]))
    [event] = recorder.events
    assert event.kind == "voice" and event.voice is not None
    assert (event.voice.data, event.voice.mime_type, event.voice.duration_seconds) == (
        b"audio-bytes", "audio/webm", 4,
    )  # fmt: skip


async def test_a_file_from_elsewhere_is_never_fetched_with_the_token(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel, recorder = listening(family, fake_slack)
    on_slack(family, family.erin)
    sneaky = fake_slack.add_file(b"x", "image/png")
    sneaky["url_private_download"] = sneaky["url_private"] = "https://evil.test/steal"
    await channel.dispatch(fake_slack.dm(MICHAEL, "look", files=[sneaky]))
    [event] = recorder.events
    assert event.kind == "text" and event.text == "look"


async def test_reactions_go_both_ways_by_slacks_names(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel, recorder = listening(family, fake_slack)
    erin = on_slack(family, family.erin)
    sent = await channel.send_text(erin, "Approve the expense?")
    _, ts = channel.where(sent) or ("", "")
    await channel.dispatch(fake_slack.react(MICHAEL, "+1::skin-tone-2", ts))
    [event] = recorder.events
    assert event.kind == "reaction" and event.reaction is not None
    assert (event.reaction.added, event.reaction.message_id) == (("👍",), sent)
    await channel.react(erin, sent, "👀")
    await channel.react(erin, sent, "🦜")  # no Slack name here: nothing sent
    assert [(c["name"], c["timestamp"]) for c in fake_slack.calls("reactions.add")] == [
        ("eyes", ts)
    ]


async def test_a_picture_goes_out_through_slacks_upload(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel = make_channel(family, fake_slack)
    erin = on_slack(family, family.erin)
    sent = await channel.send_photo(erin, b"\x89PNG\r\n\x1a\nbytes", "Step 2")
    [done] = fake_slack.calls("files.completeUploadExternal")
    assert done["channel_id"] == "DMICHAEL" and done["initial_comment"] == "Step 2"
    file_id = done["files"][0]["id"]
    assert fake_slack.state.uploads[file_id] == b"\x89PNG\r\n\x1a\nbytes"
    await channel.react(erin, sent, "👀")  # a file isn't a message to react to
    assert fake_slack.calls("reactions.add") == []


async def test_slash_themi_runs_a_chat_command(family: SeededFamily, fake_slack: FakeSlack) -> None:
    channel, recorder = listening(family, fake_slack)
    on_slack(family, family.erin)
    await channel.publish_commands(
        [("pause", "Pause Themi's messages"), ("site", "A sign-in link")]
    )
    await channel.dispatch(fake_slack.slash(MICHAEL, "pause 2 hours"))
    await channel.dispatch(fake_slack.slash(MICHAEL, "/site"))
    assert [e.text for e in recorder.events] == ["/pause 2 hours", "/site"]
    await channel.dispatch(fake_slack.slash(MICHAEL, ""))
    menu = fake_slack.calls("chat.postEphemeral")[-1]["text"]
    assert "/themi pause: Pause Themi's messages" in menu and "/themi site" in menu
    await channel.dispatch(fake_slack.slash(STRANGER, "pause"))
    assert len(recorder.events) == 2
    assert fake_slack.calls("chat.postEphemeral")[-1]["user"] == STRANGER


async def test_commands_in_themis_words_are_written_the_slack_way(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    channel = make_channel(family, fake_slack)
    erin = on_slack(family, family.erin)
    await channel.publish_commands([("pause", "Pause"), ("site", "Sign in")])
    await channel.send_text(
        erin, "Paused. Send /pause off to undo, or see https://themi.test/site."
    )
    assert fake_slack.texts(MICHAEL) == [
        "Paused. Send /themi pause off to undo, or see https://themi.test/site."
    ]


async def test_a_reaction_taken_back_comes_as_removed(
    family: SeededFamily, fake_slack: FakeSlack
) -> None:
    """F38c: Slack's reaction_removed is a Reaction with `removed`, and `added` empty."""
    channel, recorder = listening(family, fake_slack)
    erin = on_slack(family, family.erin)
    sent = await channel.send_text(erin, "Added olive oil.")
    _, ts = channel.where(sent) or ("", "")
    await channel.dispatch(fake_slack.react(MICHAEL, "-1", ts, removed=True))
    [event] = recorder.events
    assert event.reaction is not None
    assert (event.reaction.added, event.reaction.removed) == ((), ("👎",))
