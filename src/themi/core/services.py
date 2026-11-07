"""Everything the agent and its tools reach, in one place.

Later prompts plug in by adding to the lists here: approvals register an
awaiting-item source and a button handler, rules and memory fill in
`rules()` and `facts_for()`, the energy engine replaces `energy`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from themi.accounts import AccountStore, Member
from themi.accounts.household import HouseholdSettings
from themi.accounts.preferences import Preferences
from themi.ai.router import AIRouter
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy
from themi.channels.calibration import PdaCalibrator
from themi.channels.events import InboundEvent
from themi.channels.outbox import Outbox
from themi.core.kept_pictures import KeptPictures
from themi.core.prompts import OpenItem
from themi.core.tools import ToolRegistry
from themi.modules.prompt import PromptFragment, compose_system
from themi.modules.registry import Registry
from themi.modules.web import WebPages

if TYPE_CHECKING:
    from themi.core.routing import EmbeddingRouter
    from themi.core.rules import Rulebook
    from themi.core.which_task import TaskNamer
    from themi.energy.outcomes import OutcomeTracker

Decision = Literal["yes", "no", "later"]


class EnergyLabeler(Protocol):
    def label(self, member: Member) -> str: ...

    def suggested_level(self, member: Member) -> str | None: ...

    def observe_inbound(self, member: Member) -> None: ...

    def record(self, member: Member, source: str, value: float, note: str = "") -> bool: ...


class NoEnergyReadYet:
    """For tests and tools that run without the energy model."""

    def label(self, member: Member) -> str:
        return "no read yet"

    def suggested_level(self, member: Member) -> str | None:
        return None

    def observe_inbound(self, member: Member) -> None:
        return None

    def record(self, member: Member, source: str, value: float, note: str = "") -> bool:
        return False


@dataclass(frozen=True)
class AwaitingItem:
    """Something waiting on a yes/no from this member (an approval, a rule to lock)."""

    key: str
    summary: str
    resolve: Callable[[Decision], Awaitable[str]]  # returns what to tell the person
    # The Telegram messages that asked this person, once sent. A bare "yes" only answers
    # the item if Themi hasn't asked anything else since.
    message_ids: tuple[int, ...] = ()


AwaitingSource = Callable[[Member], list[AwaitingItem]]
OpenItemSource = Callable[[Member], list[OpenItem]]
EventHandler = Callable[[InboundEvent], Awaitable[None]]
CommandHandler = Callable[[Member, str], Awaitable[None]]  # (member, text after the command)
# For commands that need the whole message, such as what it replies to.
EventCommandHandler = Callable[[InboundEvent, str], Awaitable[None]]
# RC3a: a typed message a feature takes before the model sees it ("next" while cooking).
# (event, member, text) -> True when it was taken.
TextHandler = Callable[[InboundEvent, Member, str], Awaitable[bool]]


@dataclass
class Services(Registry):
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
    event_commands: dict[str, EventCommandHandler] = field(default_factory=dict)
    command_help: dict[str, str] = field(default_factory=dict)
    site_url: str = ""  # the website's base address, for /site links
    tool_routing: str = "groups"  # P5: or "all", every tool on every call; P7b "embeddings"
    conversation_rollout: str = "trial"  # CM1a: "off", "trial" or "on"
    group_router: EmbeddingRouter | None = None  # P7b, used when tool_routing is "embeddings"
    task_namer: TaskNamer | None = None  # P8b: which open task a message names, by meaning
    rulebook: Rulebook | None = None
    outcomes: OutcomeTracker | None = None
    # CR3: what the agent's context reads from modules, set by the module that has it.
    calendar_source: Callable[[Member], str] | None = None  # the calendar module (K1)
    lands_source: Callable[[Member], str] | None = None  # reactions (S5)
    facts_source: Callable[[Member, str], tuple[list[str], list[str]]] | None = None  # memory
    # BD1a: tool groups a member's state calls for, whatever the words (a session going on).
    group_sources: list[Callable[[Member], set[str]]] = field(default_factory=list)
    # RC1b onwards: what each action on a "recipe" button does (show, cook, grocery card...).
    recipe_buttons: dict[str, EventHandler] = field(default_factory=dict)
    text_handlers: list[TextHandler] = field(default_factory=list)  # RC3a
    web_pages: list[WebPages] = field(default_factory=list)  # CR4: modules' pages
    # CR7a: each loaded module's per-member preferences, for the settings page.
    preference_models: list[type[Preferences]] = field(default_factory=list)
    # CR7c: each loaded module's household settings, for the family and accounts pages.
    household_models: list[type[HouseholdSettings]] = field(default_factory=list)
    # CR7d: the settings form's sections from modules, as (order, template).
    settings_sections: list[tuple[int, str]] = field(default_factory=list)
    # CR8a: the system prompt's parts: the template's persona and rewordings, the rules.
    persona: str = ""
    prompt_fragments: list[PromptFragment] = field(default_factory=list)
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    # F34l: each member's latest picture, in memory only, for a follow-up (and F34o's reports).
    kept_pictures: KeptPictures = field(default_factory=KeptPictures)
    cooking_end_listeners: list[Callable[[Any, str], None]] = field(default_factory=list)

    def add_command(self, name: str, handler: CommandHandler, description: str) -> None:
        self.commands[name] = handler
        self.command_help[name] = description

    def add_event_command(self, name: str, handler: EventCommandHandler, description: str) -> None:
        """A command whose handler gets the whole message (for its Reply target, say)."""
        self.event_commands[name] = handler
        self.command_help[name] = description

    def command_menu(self) -> list[tuple[str, str]]:
        """For Telegram's command menu: (name without the slash, description)."""
        return [(name.lstrip("/"), words) for name, words in self.command_help.items()]

    def awaiting(self, member: Member) -> list[AwaitingItem]:
        return [item for source in self.awaiting_sources for item in source(member)]

    def open_items(self, member: Member) -> list[OpenItem]:
        items = [OpenItem(f"Waiting on you: {a.summary}") for a in self.awaiting(member)]
        for source in self.open_item_sources:
            items.extend(source(member))
        for row in self.outbox.queued(member.id):
            items.append(OpenItem(f"Scheduled to send later: {row['text'][:80]}"))
        return items

    def system_text(self) -> str:
        """The system prompt's stable part: the persona, then the core's and the loaded
        modules' rules (CR8a)."""
        return compose_system(self.persona, self.prompt_fragments, self.prompt_overrides)

    def calendar_context(self, member: Member) -> str:
        """Today's and tomorrow's events this person may see, for the model (K1)."""
        return self.calendar_source(member) if self.calendar_source is not None else ""

    def what_lands(self, member: Member) -> str:
        """What kinds of messages go down well with this person, in words (S5)."""
        return self.lands_source(member) if self.lands_source is not None else ""

    def rules(self, member: Member) -> tuple[list[str], list[str]]:
        """(locked household rules, the member's own personal rules), for the system prompt."""
        return self.rulebook.prompt_rules(member) if self.rulebook is not None else ([], [])

    def facts_for(self, member: Member, message: str = "") -> tuple[list[str], list[str]]:
        """(pinned facts for the system prompt, notes retrieved for this message)."""
        if self.facts_source is None:
            return [], []
        return self.facts_source(member, message)
