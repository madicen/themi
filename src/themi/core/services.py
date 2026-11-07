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
from themi.ai.router import AIRouter
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy
from themi.channels.calibration import PdaCalibrator
from themi.channels.events import InboundEvent
from themi.channels.outbox import Outbox
from themi.core.prompts import OpenItem
from themi.core.tools import ToolRegistry

if TYPE_CHECKING:
    from themi.connectors.catgenie import CatGenieWatcher
    from themi.connectors.gcal import CalendarSync
    from themi.connectors.gcal.busy import CalendarBusy
    from themi.connectors.gmail import GmailSync
    from themi.connectors.google import GoogleAccounts
    from themi.connectors.homeconnect import HomeConnectAccount
    from themi.connectors.roborock import RoborockWatcher
    from themi.connectors.thinq import ThinqWatcher
    from themi.connectors.tuya import TuyaWatcher
    from themi.core.appliances import Appliances
    from themi.core.body_double import BodyDouble
    from themi.core.breaks import Breaks
    from themi.core.burnout import Burnout
    from themi.core.buying import ThingsToBuy
    from themi.core.calls import VendorCalls
    from themi.core.chore_chart import ChartQueue
    from themi.core.conversation_mode import ConversationMode
    from themi.core.cookbook_save import CookbookSave
    from themi.core.cooking import Cooking
    from themi.core.cozyla_routines import CozylaRoutines
    from themi.core.cozyla_todos import CozylaTodos
    from themi.core.day_summary import DaySummary
    from themi.core.dishwasher import Dishwasher
    from themi.core.email_audit import EmailAudit
    from themi.core.events import Events
    from themi.core.expected import ExpectedEmails
    from themi.core.feedback import FeedbackChat
    from themi.core.feeders import Feeders
    from themi.core.focus import Focus
    from themi.core.follow_ups import FollowUps
    from themi.core.google_tasks import GoogleTasksInbox
    from themi.core.groceries import GroceryList
    from themi.core.guides import Guides
    from themi.core.habits import HabitReserve
    from themi.core.journal import Journal
    from themi.core.laundry import Laundry
    from themi.core.liaison import Liaison
    from themi.core.lists import Lists
    from themi.core.litter_box import LitterBox
    from themi.core.maintenance import Maintenance
    from themi.core.meals import Meals
    from themi.core.memory import Memory
    from themi.core.noise_digest import NoiseDigest
    from themi.core.pantry import Pantry
    from themi.core.reactions import Reactions
    from themi.core.recipe_groceries import RecipeGroceries
    from themi.core.recipe_ideas import RecipeIdeas
    from themi.core.recipes import Recipes
    from themi.core.routines import Routines
    from themi.core.routing import EmbeddingRouter
    from themi.core.rules import Rulebook
    from themi.core.safeway import SafewayCart
    from themi.core.senders import SenderSuggestions
    from themi.core.spending import Spending
    from themi.core.taking import Taking
    from themi.core.task_blocks import TaskBlocks
    from themi.core.tasks import TaskBoard
    from themi.core.travel import TravelHeadsUps
    from themi.core.triage import EmailTriage
    from themi.core.vacuum import Vacuum
    from themi.core.web_recipes import WebRecipes
    from themi.core.web_search import WebSearch
    from themi.core.which_list import WhichList
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
    event_commands: dict[str, EventCommandHandler] = field(default_factory=dict)
    command_help: dict[str, str] = field(default_factory=dict)
    site_url: str = ""  # the website's base address, for /site links
    tool_routing: str = "groups"  # P5: or "all", every tool on every call; P7b "embeddings"
    conversation_rollout: str = "trial"  # CM1a: "off", "trial" or "on"
    group_router: EmbeddingRouter | None = None  # P7b, used when tool_routing is "embeddings"
    task_namer: TaskNamer | None = None  # P8b: which open task a message names, by meaning
    rulebook: Rulebook | None = None
    memory: Memory | None = None
    outcomes: OutcomeTracker | None = None
    taskboard: TaskBoard | None = None
    habits: HabitReserve | None = None
    google: GoogleAccounts | None = None
    gmail: GmailSync | None = None
    calendar: CalendarSync | None = None
    calendars: CalendarBusy | None = None  # each person's own calendars, read (S2, K1)
    day_summary: DaySummary | None = None  # what's on someone's day (K2)
    events: Events | None = None  # calendar events made and changed from chat (K3)
    travel: TravelHeadsUps | None = None  # travel times and "time to get ready" (K4)
    task_blocks: TaskBlocks | None = None  # time blocked on calendars for tasks (K5)
    wall_routines: CozylaRoutines | None = None  # the wall's routines (C3, bug #22)
    senders: SenderSuggestions | None = None  # suggesting always-urgent senders (E1)
    email_audit: EmailAudit | None = None  # the email audit (E2)
    triage: EmailTriage | None = None
    noise: NoiseDigest | None = None  # noise emails offered together (F16b)
    expected: ExpectedEmails | None = None
    feedback: FeedbackChat | None = None
    groceries: GroceryList | None = None
    pantry: Pantry | None = None
    meals: Meals | None = None
    calls: VendorCalls | None = None
    wall: CozylaTodos | None = None  # the Cozyla wall's to-do lists, when configured
    chart_queue: ChartQueue | None = None  # chores waiting their turn for the chart (C2d)
    lists: Lists | None = None  # named lists Themi keeps (L1a)
    buying: ThingsToBuy | None = None  # things to buy that aren't food, and stores (L2a)
    spending: Spending | None = None  # takeout, eating out, business expenses (X1)
    safeway: SafewayCart | None = None  # the Safeway cart, filled by the helper (35c)
    breaks: Breaks | None = None  # a rest mode that ends with a question (B1)
    body_double: BodyDouble | None = None  # company while they work (BD1a)
    # BD1a: tool groups a member's state calls for, whatever the words (a session going on).
    group_sources: list[Callable[[Member], set[str]]] = field(default_factory=list)
    burnout: Burnout | None = None  # everything held, no demands (F22d)
    web_search: WebSearch | None = None  # looking things up online (F30d)
    guides: Guides | None = None  # the family's own guides (F29ha)
    recipes: Recipes | None = None  # the family cookbook, from its Google Doc (RC1a)
    # RC1b onwards: what each action on a "recipe" button does (show, cook, grocery card...).
    recipe_buttons: dict[str, EventHandler] = field(default_factory=dict)
    recipe_groceries: RecipeGroceries | None = None  # what a recipe needs, to the list (RC2a)
    cooking: Cooking | None = None  # cooking a recipe with Themi (RC3a)
    text_handlers: list[TextHandler] = field(default_factory=list)  # RC3a
    web_recipes: WebRecipes | None = None  # recipes from a link or a search (RC4a, RC4b)
    cookbook_save: CookbookSave | None = None  # a liked recipe into the cookbook doc (RC5)
    recipe_ideas: RecipeIdeas | None = None  # cookbook recipes the pantry covers (RC7)
    cooking_end_listeners: list[Callable[[Any, str], None]] = field(default_factory=list)
    taking: Taking | None = None  # a partner's tasks someone could take on (F29f)
    conversation: ConversationMode | None = None  # CM1a: plain chat, and the sidecar (CM1b)
    focus: Focus | None = None  # a few things for now, when it's too much (O1)
    which_list: WhichList | None = None  # which list, as a card (F17b)
    follow_ups: FollowUps | None = None  # reminders once a task is done (F17b)
    home_connect: HomeConnectAccount | None = None  # the family's Home Connect sign-in (H1)
    dishwasher: Dishwasher | None = None  # its cycles, read from Home Connect (H1)
    thinq: ThinqWatcher | None = None  # the washer and dryer, from LG ThinQ (30)
    laundry: Laundry | None = None  # wet loads moved, or rescued with a rewash (31)
    maintenance: Maintenance | None = None  # seasonal and long-term upkeep (33)
    appliances: Appliances | None = None  # how they're doing, asked in chat (F20b)
    roborock: RoborockWatcher | None = None  # the robot vacuum, from Roborock (V1)
    vacuum: Vacuum | None = None  # its chores when it needs a hand (V1)
    tuya: TuyaWatcher | None = None  # the pet feeders, from Tuya's cloud (32)
    feeders: Feeders | None = None  # their chores when one needs a hand (32)
    catgenie: CatGenieWatcher | None = None  # the litter box, from CatGenie's cloud (CG1a)
    litter_box: LitterBox | None = None  # its chores when it needs a hand (CG1b)
    reactions: Reactions | None = None  # what lands with each person (S5)
    journal: Journal | None = None  # each person's private journal of conversations (M1)
    google_tasks: GoogleTasksInbox | None = None  # Google Tasks as an inbox (GT1a)
    routines: Routines | None = None  # routines kept in Themi (R1a)
    liaison: Liaison | None = None  # notes passed on between partners (34a)

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

    def calendar_context(self, member: Member) -> str:
        """Today's and tomorrow's events this person may see, for the model (K1)."""
        return self.calendars.context(member) if self.calendars is not None else ""

    def what_lands(self, member: Member) -> str:
        """What kinds of messages go down well with this person, in words (S5)."""
        return self.reactions.picture(member) if self.reactions is not None else ""

    def rules(self, member: Member) -> tuple[list[str], list[str]]:
        """(locked household rules, the member's own personal rules), for the system prompt."""
        return self.rulebook.prompt_rules(member) if self.rulebook is not None else ([], [])

    def facts_for(self, member: Member, message: str = "") -> tuple[list[str], list[str]]:
        """(pinned facts for the system prompt, notes retrieved for this message)."""
        if self.memory is None:
            return [], []
        pinned, retrieved = self.memory.for_prompt(member, message)
        return [f.fact for f in pinned], [f.fact for f in retrieved]
