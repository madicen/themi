"""DC4: a message that carries a picture, drawn as it goes: one photo with the words as its
caption and the buttons under it, or the picture then the words, or the words alone."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tests.fixtures.family import SeededFamily
from tests.unit.test_outbox import FakeSender, at
from themi import clock
from themi.accounts import Member
from themi.channels.events import Button
from themi.channels.outbox import Outbox, Priority
from themi.channels.pda import PdaShield

PNG = b"\x89PNG\r\n\x1a\nday"
BUTTONS = (Button("Email", "morning", {"action": "email"}),)


class PictureSender(FakeSender):
    """A channel with pictures: captions up to `limit` (None: no captions with buttons;
    0: no pictures, as the website chat)."""

    def __init__(self, limit: int | None = 1024) -> None:
        super().__init__()
        self.limit = limit
        self.photos: list[tuple[bytes, str, tuple[Button, ...], str]] = []
        self.caption_edits: list[tuple[int, str, tuple[Button, ...]]] = []
        self.photo_fails = 0
        self.order: list[str] = []

    async def send_photo(
        self,
        member: Member,
        photo: bytes,
        caption: str = "",
        *,
        kind: str = "photo",
        buttons: Sequence[Button] = (),
    ) -> int:
        if self.photo_fails:
            self.photo_fails -= 1
            raise ConnectionError("upload failed")
        self.photos.append((photo, caption, tuple(buttons), kind))
        self.order.append("photo")
        return next(self._ids)

    async def send_text(self, member: Member, text: str, *args: Any, **kwargs: Any) -> int:
        self.order.append("text")
        return await super().send_text(member, text, *args, **kwargs)

    def caption_limit(self, member: Member) -> int | None:
        return self.limit

    async def edit_caption(
        self,
        member: Member,
        message_id: int,
        caption: str,
        buttons: Sequence[Button] = (),
        *,
        anyone: bool = False,
    ) -> None:
        self.caption_edits.append((message_id, caption, tuple(buttons)))


def outbox_with(family: SeededFamily, sender: FakeSender, picture: bytes | None = PNG) -> Outbox:
    outbox = Outbox(family.store, sender, PdaShield(None))
    drawn: list[dict[str, Any]] = []

    async def draw(member: Member, row: dict[str, Any]) -> bytes | None:
        drawn.append(row)
        return picture

    outbox.pictures["day_card"] = draw
    outbox.drawn = drawn  # type: ignore[attr-defined]
    return outbox


async def send(outbox: Outbox, member: Member, text: str = "Good morning, Erin.") -> Any:
    return await outbox.send(
        member, text, priority=Priority.NORMAL, buttons=BUTTONS, kind="morning",
        picture="day_card",
    )  # fmt: skip


async def test_the_picture_goes_with_the_words_as_its_caption(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender()
    outbox = outbox_with(family, sender)
    result = await send(outbox, family.erin)
    assert result.status == "sent"
    assert sender.photos == [(PNG, "Good morning, Erin.", BUTTONS, "morning")]
    assert sender.texts() == []
    assert outbox.sent_today(family.erin.id) == 1  # one message, counted once


async def test_an_edit_changes_the_caption_of_a_picture(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender()
    outbox = outbox_with(family, sender)
    result = await send(outbox, family.erin)
    assert result.message_id is not None
    assert await outbox.edit(family.erin, result.message_id, "Good morning, Erin.", ())
    assert sender.caption_edits == [(result.message_id, "Good morning, Erin.", ())]
    assert sender.edited == []
    other = await outbox.send(family.erin, "The washer finished.", priority=Priority.NORMAL)
    assert other.message_id is not None
    assert await outbox.edit(family.erin, other.message_id, "The washer is done.")
    assert sender.edited == [(other.message_id, "The washer is done.", ())]  # words: as before


async def test_words_too_long_for_a_caption_follow_the_picture(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender(limit=20)
    outbox = outbox_with(family, sender)
    long = "Good morning, Erin. A long day with many things on it."
    result = await send(outbox, family.erin, long)
    assert sender.order == ["photo", "text"]
    assert sender.photos[0][1:3] == ("", ())  # the picture alone
    assert sender.sent[0][1:3] == (long, BUTTONS)  # then the words, with the buttons
    assert outbox.sent_today(family.erin.id) == 1
    assert await outbox.edit(family.erin, result.message_id, long)
    assert sender.caption_edits == []  # the words are a message: edited as one


async def test_a_channel_without_captions_sends_the_picture_then_the_words(
    family: SeededFamily,
) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender(limit=None)  # Slack: a file carries no buttons
    outbox = outbox_with(family, sender)
    await send(outbox, family.erin)
    assert sender.order == ["photo", "text"]
    assert sender.texts() == ["Good morning, Erin."]


async def test_a_channel_without_pictures_gets_the_words(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender(limit=0)  # the website chat
    outbox = outbox_with(family, sender)
    await send(outbox, family.erin)
    assert sender.photos == [] and sender.texts() == ["Good morning, Erin."]
    assert outbox.drawn == []  # type: ignore[attr-defined]  # not even drawn


async def test_a_sender_with_no_pictures_at_all_gets_the_words(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = FakeSender()
    outbox = outbox_with(family, sender)
    await send(outbox, family.erin)
    assert sender.texts() == ["Good morning, Erin."]


async def test_a_picture_that_cant_be_drawn_leaves_the_words(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender()
    outbox = outbox_with(family, sender, picture=None)
    await send(outbox, family.erin)
    assert sender.photos == [] and sender.texts() == ["Good morning, Erin."]


async def test_a_drawing_that_fails_leaves_the_words(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender()
    outbox = Outbox(family.store, sender, PdaShield(None))

    async def broken(member: Member, row: dict[str, Any]) -> bytes | None:
        raise RuntimeError("no fonts")

    outbox.pictures["day_card"] = broken
    await send(outbox, family.erin)
    assert sender.texts() == ["Good morning, Erin."]


async def test_an_upload_that_fails_leaves_the_words(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender()
    sender.photo_fails = 1
    outbox = outbox_with(family, sender)
    result = await send(outbox, family.erin)
    assert result.status == "sent"
    assert sender.texts() == ["Good morning, Erin."]


async def test_an_unknown_picture_is_just_words(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender()
    outbox = outbox_with(family, sender)
    await outbox.send(family.erin, "hi", priority=Priority.NORMAL, picture="nothing_by_that_name")
    assert sender.texts() == ["hi"]


async def test_the_picture_is_drawn_when_it_goes_not_when_queued(family: SeededFamily) -> None:
    clock.freeze(at(21, 22))  # quiet hours: it waits
    sender = PictureSender()
    outbox = outbox_with(family, sender)
    assert (await send(outbox, family.erin)).status == "queued"
    assert outbox.drawn == []  # type: ignore[attr-defined]
    clock.freeze(at(22, 8))
    assert await outbox.flush() == 1
    assert len(outbox.drawn) == 1  # type: ignore[attr-defined]
    assert len(sender.photos) == 1


async def test_the_family_group_gets_words(family: SeededFamily) -> None:
    clock.freeze(at(21, 9))
    sender = PictureSender()
    outbox = outbox_with(family, sender)
    outbox.family_group.link(-100123, "Family", family.erin)
    await outbox.send(
        family.erin, "Who's free?", priority=Priority.NORMAL, to_group=True, picture="day_card"
    )
    await outbox.flush()
    assert sender.photos == []
