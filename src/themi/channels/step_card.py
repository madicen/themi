"""One message that moves along a run of steps (RC3a; BD1b's guided mode can share it).

The card is sent once and edited in place as buttons are tapped. A typed "next" is
answered with a fresh card at the bottom of the chat, and the old one loses its buttons, so
the current step is always where they're looking. In the family group, anyone may tap.
"""

from __future__ import annotations

from collections.abc import Sequence

from themi.accounts import Member
from themi.channels.events import Button
from themi.channels.family_group import replies_to_group
from themi.channels.outbox import Outbox, Priority


class StepCard:
    def __init__(self, outbox: Outbox, kind: str) -> None:
        self.outbox = outbox
        self.kind = kind

    async def show(
        self,
        member: Member,
        text: str,
        buttons: Sequence[Button] = (),
        *,
        message_id: int | None = None,
        in_group: bool = False,
        fresh: bool = False,
    ) -> int | None:
        """Edit the card (or send it, the first time or when `fresh`). Returns its message
        id, for the next edit."""
        group = in_group or replies_to_group(member)
        if message_id is not None and not fresh:
            edited = await self.outbox.edit(
                member, message_id, text, buttons, in_group=group, anyone=group
            )
            if edited:
                return message_id
        if message_id is not None and fresh:  # the old card keeps its words, not its buttons
            await self.outbox.edit(member, message_id, "(Carried on below.)", (), in_group=group)
        result = await self.outbox.send(
            member, text, priority=Priority.REPLY, kind=self.kind, buttons=buttons,
            link_preview=False,
        )  # fmt: skip
        if result.outbox_id is None:
            return None
        return self.outbox.message_id(result.outbox_id)
