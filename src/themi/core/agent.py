"""The agent: turns what someone sends into a reply (and actions).

For each inbound event:
- Reactions feed PDA calibration and any reaction handlers (approvals, later).
- Button taps go to the handler registered for their kind; "reply" buttons
  (two-option choices) count as if the person typed the option.
- Voice notes are transcribed first, then treated like text.
- Text feeds PDA calibration, then a bare yes/no/not-now resolves the one
  item waiting on this person, if Themi hasn't asked them another question
  since that item's message. With several waiting, Themi asks which one
  (listing them) instead of guessing. Otherwise the model
  runs a tool loop (at most `max_steps` model calls) and the final text goes
  out through the outbox as a reply. That's timed (P2a, `themi.core.timing`), and if
  it takes more than ten seconds a short "still coming" message goes first.

Failures are said plainly and briefly, never as error dumps.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
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
from themi.core.timing import SLOW_AFTER, ReplyTimer, pick_notice
from themi.core.tools import ToolContext, choose_groups
from themi.energy.remarks import energy_remark
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
FAILED_TEXT = "That didn't go through, so nothing has changed yet."
WHICH_TEXT = "Which one did you mean: {items}? Each card above has its own buttons."
NOTHING_CHANGED_TEXT = "Nothing changed there: that's already done, or already waiting for a yes."
CLAIMS_DONE = re.compile(
    r"\b(?:i've|i have|i)\s+(?:just\s+)?(?:added|put|archived|booked|sent|ordered|scheduled|"
    r"created|removed|deleted|set up|made|cleared|cancell?ed|set aside|discarded|moved|"
    r"rescheduled|changed)\b"
    r"|^(?:added|done|archived|booked|sent|ordered|scheduled|moved|rescheduled)\b"
    r"|\b(?:is|are|has been|have been|was|were)\s+(?:now\s+)?(?:added|done|archived|booked|"
    r"sent|ordered|scheduled|on the list|moved|rescheduled|deleted|cancell?ed)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _honest(reply: str, waiting: list[str], outcomes: list[str]) -> str:
    """The model sometimes says "Added X" when X is only waiting on a yes (prompt 28's evals,
    feedback bug #3), or claims success when every tool call failed (bug #5). Such replies
    are replaced: the approval card speaks for itself, and a failure is said plainly."""
    if not CLAIMS_DONE.search(reply):
        return reply
    if outcomes and "ok" not in outcomes:
        return NOTHING_CHANGED_TEXT if "declined" in outcomes else FAILED_TEXT
    if waiting:
        return "\n".join(WAITING_TEXT.format(summary=summary) for summary in waiting)
    return reply


# Bug #71: "Task 50 is taken off the list." People know tasks by name, not by number.
TASK_NUMBER = re.compile(r"\btask\s+#?(\d+)(\s*\(([^)]*)\))?", re.IGNORECASE)


def _by_name(reply: str, title_of: Callable[[int], str | None]) -> str:
    """Each "task 50" in a reply becomes the task's name in quotes ("task 7 (Clean the bird
    cage)" too); a number that isn't a task stays as it is."""

    def named(match: re.Match[str]) -> str:
        title = title_of(int(match.group(1)))
        if title is None:
            return match.group(0)
        said = match.group(3)  # quoted: a title like "Refill the water" isn't an order
        return f'"{title}"' if said is None or said.strip() == title else f'"{title}" ({said})'

    return TASK_NUMBER.sub(named, reply)


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
    def __init__(
        self,
        services: Services,
        *,
        max_steps: int = 8,
        history: int = 12,
        rng: random.Random | None = None,
    ) -> None:
        self.services = services
        self.max_steps = max_steps
        self.history = history
        self._rng = rng or random.Random()

    async def handle(self, event: InboundEvent, channel: TelegramChannel) -> None:
        member = self.services.store.get_member(event.member.id)  # settings may have changed
        if self.services.outcomes is not None:
            self.services.outcomes.observe(member, event)
        if event.kind == "reaction" and event.reaction is not None:
            self.services.calibrator.observe_reaction(member, event.reaction.added)
            for handler in self.services.reaction_handlers:
                await handler(event)
            return

        timer = ReplyTimer(self.services.store.db, member.id)  # from the message arriving
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
        energy_mark = self.services.store.db.scalar(
            "SELECT COALESCE(MAX(id), 0) FROM energy_signals"
        )
        timer.start()
        try:
            async with channel.typing(member), self._slow_notice(member, event, timer):
                reply = await self._converse(member, text, event, timer)
            self._catch_energy(member, text, energy_mark)
            async with timer.outbox():
                await self._reply(member, reply)
        finally:
            timer.finish()

    @asynccontextmanager
    async def _slow_notice(
        self, member: Member, event: InboundEvent, timer: ReplyTimer
    ) -> AsyncIterator[None]:
        """Michael's idea: a reply still coming after SLOW_AFTER seconds gets one short
        message first. Not for button taps. If the reply is ready when the time comes,
        the message doesn't go."""
        answered = False

        async def watch() -> None:
            await clock.sleep(SLOW_AFTER)
            if answered:
                return
            notice = pick_notice(self.services.store.db, member.id, self._rng)
            timer.notice = notice
            try:
                await self.services.outbox.send(
                    member, notice, priority=Priority.REPLY, kind="slow_notice"
                )
            except Exception:
                log.warning("Couldn't say a reply was slow", exc_info=True)

        if event.kind == "button":
            yield
            return
        watcher = asyncio.create_task(watch())
        try:
            yield
        finally:
            answered = True
            if timer.notice is None:
                watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher  # a notice on its way goes before the reply

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
        cards = {i for item in waiting for i in item.message_ids}  # the waiting cards themselves
        if not waiting or any(self._asked_since(member, item, cards) for item in waiting):
            return False  # nothing waiting, or Themi has asked something else since
        if len(waiting) > 1:  # a bare yes can't say which: ask, rather than guess
            names = [item.summary for item in waiting]
            listed = ", ".join(names[:-1]) + f" or {names[-1]}"
            await self._reply(member, WHICH_TEXT.format(items=listed))
            return True
        outcome = await waiting[0].resolve(decision)
        await self._reply(member, outcome)
        return True

    def _catch_energy(self, member: Member, text: str, mark: int) -> None:
        """If the turn recorded no energy remark but the message plainly has one, record it
        (the person's privacy switch still decides; see themi.energy.remarks)."""
        recorded = self.services.store.db.scalar(
            "SELECT COUNT(*) FROM energy_signals WHERE id > ? AND member_id = ? "
            "AND source IN ('text_note', 'day_level')",
            (mark, member.id),
        )
        if recorded:
            return
        remark = energy_remark(text)
        if remark is not None:
            self.services.energy.record(
                member, remark.source, remark.value, f"said: {remark.words}"
            )

    def _waiting_since(self, member: Member, mark: int) -> list[str]:
        """Approvals created for this member after `mark` that are still waiting on a yes."""
        rows = self.services.store.db.query(
            "SELECT summary FROM pending_actions WHERE id > ? AND member_id = ? "
            "AND status = 'pending' ORDER BY id",
            (mark, member.id),
        )
        return [r["summary"] for r in rows]

    def _asked_since(
        self, member: Member, item: AwaitingItem, cards: frozenset[int] | set[int] = frozenset()
    ) -> bool:
        """Has Themi asked this person a question since the item's own message? Then a bare
        "yes" may answer that question, so the model decides. Other waiting cards (`cards`)
        don't count: "Go ahead, or not now?" on the next card isn't a different question."""
        if not item.message_ids:
            return False
        rows = self.services.store.db.query(
            "SELECT telegram_message_id FROM message_log WHERE member_id = ? "
            "AND direction = 'out' AND kind != 'edit' AND telegram_message_id > ? "
            "AND text LIKE '%?%'",
            (member.id, max(item.message_ids)),
        )
        return any(r["telegram_message_id"] not in cards for r in rows)

    async def _converse(
        self, member: Member, text: str, event: InboundEvent, timer: ReplyTimer
    ) -> str:
        services = self.services
        family = services.store.get_family()
        timezone = family.timezone if family else "UTC"
        pinned, notes = services.facts_for(member, text)
        household, personal = services.rules(member)
        system = build_system(household, pinned, personal_rules=personal, owner=member.name)
        history = self._history(member, event)
        turn = build_turn(
            member,
            text,
            local_now=to_local(clock.now(), timezone),
            energy_label=services.energy.label(member),
            open_items=services.open_items(member),
            history=history,
            notes=notes,
            timezone=timezone,
            calendars=services.calendar_context(member),
        )
        messages = [Message.user(turn)]
        client = services.router.client_for(member.id, AITask.CONVERSATION)
        before = next((m.text for m in reversed(history) if m.direction == "in"), "")
        # P1: the tools this message and the last few call for; more_tools adds to them.
        groups = choose_groups([text, *(m.text for m in history[-4:])])
        ctx = ToolContext(member, services, request_text=text, previous_text=before, groups=groups)
        # Approvals made this turn, by any path (a staged tool, the pantry, the calendar...).
        mark = services.store.db.scalar("SELECT COALESCE(MAX(id), 0) FROM pending_actions")
        used_tools = False
        try:
            for step in range(1, self.max_steps + 1):
                response = await client.chat(system, messages, services.tools.specs(ctx.groups))
                if not response.tool_calls:
                    reply = response.text.strip() or ("Done." if used_tools else TANGLED_TEXT)
                    reply = _by_name(reply, self._task_title)
                    return _honest(reply, self._waiting_since(member, mark), ctx.outcomes)
                used_tools = True
                messages.append(response.message)
                results = []
                for call in response.tool_calls:
                    with timer.tool(call.name, after_model=step):
                        results.append(await services.tools.run(call, ctx))
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

    def _task_title(self, task_id: int) -> str | None:
        row = self.services.store.db.one("SELECT title FROM tasks WHERE id = ?", (task_id,))
        return row["title"] if row else None

    async def _reply(self, member: Member, text: str) -> None:
        await self.services.outbox.send(member, text, priority=Priority.REPLY)
