"""The agent: turns what someone sends into a reply (and actions).

For each inbound event:
- Reactions feed PDA calibration and any reaction handlers (approvals, later).
- Button taps go to the handler registered for their kind; "reply" buttons
  (two-option choices) count as if the person typed the option.
- Voice notes are transcribed first, then treated like text.
- Text feeds PDA calibration, then a bare yes/no/not-now resolves the one
  item waiting on this person, if there's exactly one and Themi hasn't asked
  them another question since that item's message. Otherwise the model
  runs a tool loop (at most `max_steps` model calls) and the final text goes
  out through the outbox as a reply.

Failures are said plainly and briefly, never as error dumps.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from themi import clock
from themi.accounts import Member
from themi.ai.errors import RefusalError
from themi.ai.router import AllProvidersFailed
from themi.ai.settings import AITask
from themi.ai.types import Message
from themi.channels.events import InboundEvent
from themi.channels.outbox import Priority
from themi.core.prompts import build_system, build_turn
from themi.core.services import AwaitingItem, Decision, Services
from themi.core.tools import ToolContext
from themi.localtime import to_local

if TYPE_CHECKING:
    from themi.channels.telegram import TelegramChannel

log = logging.getLogger(__name__)

YES_WORDS = frozenset(
    {
        "yes",
        "y",
        "yep",
        "yeah",
        "yup",
        "ok",
        "okay",
        "sure",
        "go ahead",
        "do it",
        "sounds good",
        "👍",
        "✅",
    }
)
# A reply that says something was done while it's only waiting on a yes is replaced.
WAITING_TEXT = "{summary}: that's waiting for a yes on the card above."
CLAIMS_DONE = re.compile(
    r"\b(?:i've|i have|i)\s+(?:just\s+)?(?:added|put|archived|booked|sent|ordered|scheduled|"
    r"created|removed|deleted|set up|made)\b"
    r"|^(?:added|done|archived|booked|sent|ordered|scheduled)\b"
    r"|\b(?:is|are|has been|have been|was|were)\s+(?:now\s+)?(?:added|done|archived|booked|"
    r"sent|ordered|scheduled|on the list)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _honest(reply: str, waiting: list[str]) -> str:
    """The model sometimes says "Added X" when X is only waiting on a yes (prompt 28's evals,
    feedback bug #3). The approval card speaks for itself, so such a reply is replaced."""
    if not waiting or not CLAIMS_DONE.search(reply):
        return reply
    return "\n".join(WAITING_TEXT.format(summary=summary) for summary in waiting)


NO_WORDS = frozenset({"no", "n", "nope", "nah", "skip", "skip it", "no thanks", "leave it"})
LATER_WORDS = frozenset({"not now", "later", "maybe later", "not yet", "💤"})

SETUP_NEEDED_TEXT = (
    "I can't reach an AI service yet. Once an AI key is added in your Themi settings, "
    "I can pick this up."
)
BUSY_TEXT = (
    "The AI service is busy at the moment, so I couldn't answer that one. "
    "It usually clears up within a few minutes."
)
DECLINED_TEXT = "That one's outside what I can help with, sorry."
TANGLED_TEXT = "I got a bit tangled up working on that, so I've stopped there."
VOICE_FAILED_TEXT = "I couldn't make out that voice note. A typed message works too."


class Agent:
    def __init__(self, services: Services, *, max_steps: int = 8, history: int = 12) -> None:
        self.services = services
        self.max_steps = max_steps
        self.history = history

    async def handle(self, event: InboundEvent, channel: TelegramChannel) -> None:
        member = self.services.store.get_member(event.member.id)  # settings may have changed
        if self.services.outcomes is not None:
            self.services.outcomes.observe(member, event)
        if event.kind == "reaction" and event.reaction is not None:
            self.services.calibrator.observe_reaction(member, event.reaction.added)
            for handler in self.services.reaction_handlers:
                await handler(event)
            return

        if event.kind == "button" and event.button is not None:
            if event.button.kind != "reply":
                handler = self.services.button_handlers.get(event.button.kind)
                if handler is None:
                    log.info("No handler for %s buttons; ignoring a tap", event.button.kind)
                    return
                await handler(event)
                return
            text = str(event.button.payload.get("text", event.button.label))
        elif event.kind == "voice" and event.voice is not None:
            async with channel.typing(member):
                transcript = await self._transcribe(member, event)
            if transcript is None:
                await self._reply(member, VOICE_FAILED_TEXT)
                return
            text = transcript
        else:
            text = event.text

        if not text.strip():
            return
        if text.startswith("/"):
            command, _, argument = text.partition(" ")
            name = command.lower().split("@")[0]
            if (event_handler := self.services.event_commands.get(name)) is not None:
                await event_handler(event, argument.strip())
                return
            handler = self.services.commands.get(name)
            if handler is not None:
                await handler(member, argument.strip())
                return
        self.services.calibrator.observe_text(member, text)
        self.services.energy.observe_inbound(member)
        if await self._fast_path(member, text):
            return
        async with channel.typing(member):
            reply = await self._converse(member, text, event)
        await self._reply(member, reply)

    # ----- steps --------------------------------------------------------------

    async def _transcribe(self, member: Member, event: InboundEvent) -> str | None:
        assert event.voice is not None
        client = self.services.router.client_for(member.id, AITask.TRANSCRIPTION)
        try:
            result = await client.transcribe(event.voice.data, event.voice.mime_type)
        except Exception as exc:
            log.warning("Transcription failed for member %s (%s)", member.id, type(exc).__name__)
            return None
        text = result.text.strip()
        if not text:
            return None
        self.services.store.log_message(member.id, "in", text, "transcript", event.message_id)
        return text

    async def _fast_path(self, member: Member, text: str) -> bool:
        normalised = text.strip().lower().rstrip("!. ")
        decision: Decision | None
        if normalised in YES_WORDS:
            decision = "yes"
        elif normalised in NO_WORDS:
            decision = "no"
        elif normalised in LATER_WORDS:
            decision = "later"
        else:
            decision = None
        if decision is None:
            return False
        waiting = self.services.awaiting(member)
        if len(waiting) != 1 or self._asked_since(member, waiting[0]):
            return False
        outcome = await waiting[0].resolve(decision)
        await self._reply(member, outcome)
        return True

    def _asked_since(self, member: Member, item: AwaitingItem) -> bool:
        """Has Themi asked this person a question since the item's own message?
        Then a bare "yes" may answer that question, so the model decides."""
        if not item.message_ids:
            return False
        row = self.services.store.db.one(
            "SELECT 1 FROM message_log WHERE member_id = ? AND direction = 'out' "
            "AND kind != 'edit' AND telegram_message_id > ? AND text LIKE '%?%' LIMIT 1",
            (member.id, max(item.message_ids)),
        )
        return row is not None

    async def _converse(self, member: Member, text: str, event: InboundEvent) -> str:
        services = self.services
        family = services.store.get_family()
        timezone = family.timezone if family else "UTC"
        pinned, notes = services.facts_for(member, text)
        household, personal = services.rules(member)
        system = build_system(household, pinned, personal_rules=personal, owner=member.name)
        turn = build_turn(
            member,
            text,
            local_now=to_local(clock.now(), timezone),
            energy_label=services.energy.label(member),
            open_items=services.open_items(member),
            history=self._history(member, event),
            notes=notes,
            timezone=timezone,
        )
        messages = [Message.user(turn)]
        tools = services.tools.specs()
        client = services.router.client_for(member.id, AITask.CONVERSATION)
        ctx = ToolContext(member, services, request_text=text)
        used_tools = False
        try:
            for _ in range(self.max_steps):
                response = await client.chat(system, messages, tools)
                if not response.tool_calls:
                    reply = response.text.strip() or ("Done." if used_tools else TANGLED_TEXT)
                    return _honest(reply, ctx.staged)
                used_tools = True
                messages.append(response.message)
                results = [await services.tools.run(call, ctx) for call in response.tool_calls]
                messages.append(Message.tool_results(*results))
        except RefusalError:
            return DECLINED_TEXT
        except AllProvidersFailed as exc:
            log.warning("No AI backend answered member %s: %s", member.id, exc)
            return SETUP_NEEDED_TEXT if exc.needs_setup else BUSY_TEXT
        log.warning("Agent hit its step limit for member %s", member.id)
        return TANGLED_TEXT

    def _history(self, member: Member, event: InboundEvent) -> list:
        recent = self.services.store.recent_messages(member.id, self.history + 3)
        # Drop this event's own entries (the message, its voice note marker, its transcript).
        while (
            recent
            and recent[-1].direction == "in"
            and (event.message_id is None or recent[-1].telegram_message_id == event.message_id)
        ):
            recent.pop()
        return recent[-self.history :]

    async def _reply(self, member: Member, text: str) -> None:
        await self.services.outbox.send(member, text, priority=Priority.REPLY)
