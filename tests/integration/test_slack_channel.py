"""SL1-SL4: the Slack channel against a local fake of Slack, over real HTTP (and, for the
socket, a real WebSocket)."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes.slack_api import APP_TOKEN, BOT_TOKEN, MICHAEL, FakeSlack
from tests.fixtures.family import SeededFamily
from themi.accounts import Member
from themi.channels.slack import NAME, SlackChannel
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
