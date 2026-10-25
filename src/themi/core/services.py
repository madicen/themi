"""Everything the agent and its tools reach, in one place.

Later prompts plug in by adding to the lists here: approvals register an
awaiting-item source and a button handler, rules and memory fill in
`rules()` and `facts_for()`, the energy engine replaces `energy`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from themi.accounts import AccountStore, Member
from themi.ai.router import AIRouter
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy
from themi.channels.calibration import PdaCalibrator
from themi.channels.events import InboundEvent
from themi.channels.outbox import Outbox
from themi.core.prompts import OpenItem
from themi.core.tools import ToolRegistry

if TYPE_CHECKING:
    from themi.core.memory import Memory
    from themi.core.rules import Rulebook

Decision = Literal["yes", "no", "later"]


class EnergyLabeler(Protocol):
    def label(self, member: Member) -> str: ...


class NoEnergyReadYet:
    """Until the energy model exists (prompt 18)."""

    def label(self, member: Member) -> str:
        return "no read yet"


@dataclass(frozen=True)
class AwaitingItem:
    """Something waiting on a yes/no from this member (an approval, a rule to lock)."""

    key: str
    summary: str
    resolve: Callable[[Decision], Awaitable[str]]  # returns what to tell the person


AwaitingSource = Callable[[Member], list[AwaitingItem]]
OpenItemSource = Callable[[Member], list[OpenItem]]
EventHandler = Callable[[InboundEvent], Awaitable[None]]
CommandHandler = Callable[[Member, str], Awaitable[None]]  # (member, text after the command)


@dataclass
class Services:
    store: AccountStore
    ai_settings: AISettingsStore
    router: AIRouter
    outbox: Outbox
    calibrator: PdaCalibrator
    tools: ToolRegistry
    autonomy: Autonomy
    energy: EnergyLabeler = field(default_factory=NoEnergyReadYet)
    awaiting_sources: list[AwaitingSource] = field(default_factory=list)
    open_item_sources: list[OpenItemSource] = field(default_factory=list)
    button_handlers: dict[str, EventHandler] = field(default_factory=dict)
    reaction_handlers: list[EventHandler] = field(default_factory=list)
    commands: dict[str, CommandHandler] = field(default_factory=dict)
    rulebook: Rulebook | None = None
    memory: Memory | None = None

    def awaiting(self, member: Member) -> list[AwaitingItem]:
        return [item for source in self.awaiting_sources for item in source(member)]

    def open_items(self, member: Member) -> list[OpenItem]:
        items = [OpenItem(f"Waiting on you: {a.summary}") for a in self.awaiting(member)]
        for source in self.open_item_sources:
            items.extend(source(member))
        for row in self.outbox.queued(member.id):
            items.append(OpenItem(f"Scheduled to send later: {row['text'][:80]}"))
        return items

    def rules(self) -> list[str]:
        """Locked household rules, for the system prompt."""
        return self.rulebook.locked_texts() if self.rulebook is not None else []

    def facts_for(self, member: Member, message: str = "") -> tuple[list[str], list[str]]:
        """(pinned facts for the system prompt, notes retrieved for this message)."""
        if self.memory is None:
            return [], []
        pinned, retrieved = self.memory.for_prompt(member, message)
        return [f.fact for f in pinned], [f.fact for f in retrieved]
