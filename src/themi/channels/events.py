"""What arrives from a chat, in a form the agent core doesn't need Telegram to read."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from themi.accounts.models import Member

if TYPE_CHECKING:
    from themi.channels.outbox import Outbox
    from themi.channels.telegram import TelegramChannel

EventKind = Literal["text", "voice", "button", "reaction"]


@dataclass(frozen=True)
class Button:
    """One inline button. `kind` and `payload` stay on the server; only a token travels."""

    label: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceNote:
    data: bytes = field(repr=False)
    mime_type: str
    duration_seconds: int


@dataclass(frozen=True)
class ButtonPress:
    label: str
    kind: str
    payload: dict[str, Any]
    message_id: int | None


@dataclass(frozen=True)
class Reaction:
    added: tuple[str, ...]  # emoji newly added to the message
    message_id: int


@dataclass(frozen=True)
class InboundEvent:
    kind: EventKind
    member: Member
    chat_id: int
    message_id: int | None
    received_at: datetime
    update_id: int
    text: str = ""
    voice: VoiceNote | None = None
    button: ButtonPress | None = None
    reaction: Reaction | None = None


class InboundHandler(Protocol):
    async def handle(self, event: InboundEvent, channel: TelegramChannel) -> None: ...


class EchoHandler:
    """Stand-in until the agent core exists (prompt 09): proves the plumbing end to end."""

    def __init__(self, outbox: Outbox) -> None:
        self.outbox = outbox

    async def handle(self, event: InboundEvent, channel: TelegramChannel) -> None:
        from themi.channels.outbox import Priority

        if event.kind == "text":
            reply = f"You said: {event.text}"
        elif event.kind == "voice" and event.voice is not None:
            reply = f"Got a {event.voice.duration_seconds}s voice note."
        elif event.kind == "button" and event.button is not None:
            reply = f"You chose: {event.button.label}"
        else:
            return
        await self.outbox.send(event.member, reply, priority=Priority.REPLY)
