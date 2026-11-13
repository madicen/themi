"""DC5: the morning message as a picture of the day, its words the caption, its buttons
under it. As in the morning message scenarios: Thursday 22 October, Erin's message at 7:15
waits for her quiet hours to end and goes at 8. Drawings are in the family template, and
the picture is on for everyone (Michael, 2026-11-13)."""

from __future__ import annotations

from typing import Any

from tests.fakes.gcal_api import FakeGcal
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import linked
from tests.scenarios.test_morning_message import ALL_FOUR, MORNING, counted, overnight
from themi.channels.channel_set import ChannelSet
from themi.core import keys
from themi.standard.drawings import DrawingsPreferences

__all__ = ["linked"]


def caption_edits(scenario: Scenario) -> list[dict[str, Any]]:
    chat = scenario.member("Erin").telegram_user_id
    return [p for p in scenario.telegram.calls("editMessageCaption") if int(p["chat_id"]) == chat]


async def test_the_morning_message_is_a_picture_with_its_words_and_buttons(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await overnight(scenario, linked)
    assert scenario.pictures("Erin") == []  # held by quiet hours: nothing drawn yet
    assert await scenario.advance(minutes=45) == [MORNING]
    (picture,) = scenario.pictures("Erin")
    assert picture["caption"] == MORNING
    assert scenario.last_buttons("Erin") == ALL_FOUR
    assert counted(scenario) == 1


async def test_a_tap_edits_the_caption_and_keeps_the_picture(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await overnight(scenario, linked)
    await scenario.advance(minutes=45)
    replies = await scenario.tap("Erin", "Email")
    assert replies == ["New mail from the bank."]
    (edit,) = caption_edits(scenario)
    assert edit["caption"] == MORNING
    assert scenario.telegram.calls("editMessageText") == []
    assert len(scenario.pictures("Erin")) == 1  # the picture isn't sent again


async def test_with_the_picture_off_the_morning_is_words_as_before(
    scenario: Scenario, linked: FakeGcal
) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, DrawingsPreferences, picture_morning=False)
    await overnight(scenario, linked)
    assert await scenario.advance(minutes=45) == [MORNING]
    assert scenario.pictures("Erin") == []
    assert scenario.last_buttons("Erin") == ALL_FOUR


async def test_turned_off_while_it_waits_it_goes_as_words(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await overnight(scenario, linked)  # queued at 7:15 with the picture
    erin = scenario.member("Erin")
    scenario.app.store.save_preferences(erin, erin.id, DrawingsPreferences, picture_morning=False)
    assert await scenario.advance(minutes=45) == [MORNING]
    assert scenario.pictures("Erin") == []


async def test_a_picture_that_cant_be_drawn_leaves_the_words(
    scenario: Scenario, linked: FakeGcal
) -> None:
    def broken(svg: str, width: int | None) -> bytes:
        raise ValueError("no fonts here")

    scenario.app.services.get(keys.drawings).renderer.convert = broken
    await overnight(scenario, linked)
    assert await scenario.advance(minutes=45) == [MORNING]
    assert scenario.pictures("Erin") == []
    assert scenario.last_buttons("Erin") == ALL_FOUR
    assert counted(scenario) == 1


async def test_the_noon_recap_stays_words(scenario: Scenario, linked: FakeGcal) -> None:
    from tests.scenarios.test_morning_message import at, to

    await overnight(scenario, linked)
    await scenario.advance(minutes=45)
    to(at(12))
    await scenario.run_periodic("calendar.morning_recap")
    await scenario.advance(minutes=1)
    assert len(scenario.pictures("Erin")) == 1  # only the morning's


class _Words:
    async def send_text(self, *args: Any, **kwargs: Any) -> int:
        return 1


class _Pictures(_Words):
    async def send_photo(self, *args: Any, **kwargs: Any) -> int:
        return 2


class _Captions(_Pictures):
    def caption_limit(self, member: Any) -> int:
        return 1024


def test_each_channel_says_how_it_shows_a_picture(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    for channel, limit in ((_Captions(), 1024), (_Pictures(), None), (_Words(), 0)):
        channels = ChannelSet()
        channels.add("telegram", channel)  # type: ignore[arg-type]
        assert channels.caption_limit(erin) == limit
