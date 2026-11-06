"""Assemble Themi from its parts.

One function builds the whole object graph, so the CLI, the scenario
harness and `themi run` (prompt 10) all run the same wiring.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from themi.accounts import AccountStore
from themi.ai.embeddings import RouterEmbedder, VectorCache
from themi.ai.retry import Sleep
from themi.ai.router import HEDGE_AFTER, AIRouter, ProviderFactory
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy, ExecutorRegistry
from themi.backup import BackupConfig, Backups
from themi.backup.job import BackupJob
from themi.channels.calibration import PdaCalibrator
from themi.channels.outbox import Outbox
from themi.channels.pda import AIRewriter, PdaShield
from themi.channels.telegram import TelegramChannel
from themi.connectors.catgenie import CatGenieAccount, CatGenieConfig, CatGenieWatcher
from themi.connectors.cozyla import CozylaClient
from themi.connectors.gcal import CalendarSync
from themi.connectors.gcal.busy import CalendarBusy
from themi.connectors.gkeep import KeepFactory
from themi.connectors.gmail import GmailSync, install_executors
from themi.connectors.google import GoogleAccounts, GoogleConfig, GoogleOAuth
from themi.connectors.homeconnect import HomeConnectAccount, HomeConnectClient
from themi.connectors.ourgroceries import GroceryListClient, GroceryMirror
from themi.connectors.roborock import RoborockAccount, RoborockLogin, RoborockWatcher
from themi.connectors.search import SearchBackend
from themi.connectors.thinq import ThinqAccount, ThinqConfig, ThinqPush, ThinqWatcher
from themi.connectors.travel import TravelClient
from themi.connectors.tuya import TuyaAccount, TuyaConfig, TuyaWatcher
from themi.core.agent import Agent
from themi.core.appliances import Appliances
from themi.core.approvals import ApprovalsUI
from themi.core.breaks import Breaks
from themi.core.burnout import Burnout
from themi.core.buying import ThingsToBuy
from themi.core.calendar import TaskCalendar
from themi.core.calls import VendorCalls
from themi.core.checkin_reviews import CheckinReviews
from themi.core.commands import Commands
from themi.core.conversation_mode import ConversationMode
from themi.core.cozyla_chores import CozylaChores
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
from themi.core.google_tasks_list import GoogleTaskList
from themi.core.groceries import GroceryList
from themi.core.guides import Guides
from themi.core.habits import HabitReserve
from themi.core.journal import Journal
from themi.core.keep_groceries import KeepGroceries, KeepLinks
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
from themi.core.reminders import Reminders
from themi.core.routines import Routines
from themi.core.routines_wall import RoutinesWall
from themi.core.routing import EmbeddingRouter
from themi.core.rules import Rulebook
from themi.core.safeway import SafewayCart
from themi.core.senders import SenderSuggestions
from themi.core.services import Services
from themi.core.spending import Spending
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.taking import Taking
from themi.core.task_blocks import TaskBlocks
from themi.core.tasks import TaskBoard
from themi.core.tools import ToolRegistry
from themi.core.travel import TravelHeadsUps
from themi.core.triage import EmailTriage
from themi.core.vacuum import Vacuum
from themi.core.web_search import WebSearch
from themi.core.which_list import WhichList
from themi.core.which_task import TaskNamer
from themi.core.wrong_replies import WrongReplies
from themi.energy import EnergyModel
from themi.energy.matching import Matcher
from themi.energy.outcomes import OutcomeTracker
from themi.energy.windows import EnergyReceptivity
from themi.scheduler import Scheduler
from themi.storage.db import Database
from themi.storage.secrets import Cipher
from themi.updates import ServerControl

ChannelFactory = Callable[[AccountStore], TelegramChannel]


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    every: timedelta
    run: Callable[[], Awaitable[object]]


@dataclass
class App:
    db: Database
    store: AccountStore
    ai_settings: AISettingsStore
    router: AIRouter
    channel: TelegramChannel
    outbox: Outbox
    services: Services
    agent: Agent
    approvals: ApprovalsUI
    rulebook: Rulebook
    periodic: list[PeriodicTask] = field(default_factory=list)
    # Queued background work (the Runtime adds the periodic tasks to it too).
    scheduler: Scheduler | None = None
    server: ServerControl | None = None  # updates and restarts from the website (D3a)


def build_app(
    db: Database,
    cipher: Cipher,
    make_channel: ChannelFactory,
    *,
    provider_factory: ProviderFactory | None = None,
    sleep: Sleep = asyncio.sleep,
    google: GoogleConfig | None = None,
    grocery_list: GroceryListClient | None = None,
    cozyla: CozylaClient | None = None,
    travel: TravelClient | None = None,
    search: SearchBackend | None = None,
    home_connect: HomeConnectClient | None = None,
    thinq: ThinqConfig | None = None,
    roborock: RoborockLogin | None = None,
    tuya: TuyaConfig | None = None,
    catgenie: CatGenieConfig | None = None,
    keep: KeepFactory | None = None,
    backup: BackupConfig | None = None,
    tool_routing: str = "groups",
    conversation_mode: str = "trial",
    control_dir: Path | None = None,
    hedge_after: float | None = HEDGE_AFTER,
) -> App:
    store = AccountStore(db, cipher)
    ai_settings = AISettingsStore(db, cipher)
    router = AIRouter(ai_settings, factory=provider_factory, sleep=sleep, hedge_after=hedge_after)
    channel = make_channel(store)
    energy = EnergyModel(store)
    outbox = Outbox(store, channel, PdaShield(AIRewriter(router)), EnergyReceptivity(energy))
    outcomes = OutcomeTracker(store)
    outbox.sent_listeners.append(outcomes.on_sent)
    services = Services(
        tool_routing=tool_routing,
        conversation_rollout=conversation_mode,
        group_router=EmbeddingRouter(RouterEmbedder(router), VectorCache(db)),
        task_namer=TaskNamer(RouterEmbedder(router), VectorCache(db)),
        store=store,
        ai_settings=ai_settings,
        router=router,
        outbox=outbox,
        calibrator=PdaCalibrator(store),
        tools=ToolRegistry(list(STARTER_TOOLS)),
        autonomy=Autonomy(store, ExecutorRegistry()),
        energy=energy,
        outcomes=outcomes,
    )
    approvals = ApprovalsUI(services.autonomy, outbox)
    approvals.install(services)
    rulebook = Rulebook(services.autonomy, outbox)
    rulebook.install(services)
    services.memory = Memory(db, rulebook)
    journal = Journal(services)
    journal.install()
    if google is not None:
        services.google = GoogleAccounts(store, GoogleOAuth(db, store.cipher, google))
        services.gmail = GmailSync(store, services.google, outbox)
        install_executors(services.autonomy.executors, services.gmail)
        EmailTriage(services, services.gmail).install()
        SenderSuggestions(services).install()
        ExpectedEmails(services, services.gmail).install()
        NoiseDigest(services, approvals, services.gmail).install()
    groceries = GroceryList(services)
    groceries.install()
    safeway = SafewayCart(services, groceries)
    safeway.install()
    lists = Lists(services)
    lists.install()
    ThingsToBuy(services, lists).install()
    WhichList(services).install()
    Spending(services).install()
    Liaison(services).install()
    Breaks(services).install()
    pantry = Pantry(services, groceries)
    pantry.install()
    tasks = TaskBoard(services, Matcher(store, energy))
    tasks.install()
    FollowUps(services, tasks).install()
    if services.gmail is not None:
        EmailAudit(services, tasks).install()
    reminders = Reminders(services, tasks)
    reminders.install()
    day_summary = DaySummary(services, tasks)
    day_summary.install()
    Focus(services, tasks, day_summary).install()
    Taking(services, tasks).install()
    Guides(services).install()
    burnout = Burnout(services, tasks)
    burnout.install()
    ConversationMode(services).install()
    reviews = CheckinReviews(services)
    reviews.install()
    Meals(services, pantry).install()
    VendorCalls(services, tasks).install()
    scheduler = Scheduler(db)
    calendar_busy: CalendarBusy | None = None
    task_blocks: TaskBlocks | None = None
    if services.google is not None:
        services.calendar = CalendarSync(store, services.google)
        TaskCalendar(services, tasks, services.calendar, scheduler).install()
        calendar_busy = CalendarBusy(store, services.calendar)
        services.calendars = calendar_busy
        outbox.calendar_blocks = calendar_busy.blocks
        energy.calendar_blocks = calendar_busy.blocks
        Events(services).install()
        task_blocks = TaskBlocks(services, tasks)
        task_blocks.install()
    WebSearch(services, search).install()  # F30d: says how to set it up without a key
    travel_heads_ups: TravelHeadsUps | None = None
    if travel is not None:
        travel_heads_ups = TravelHeadsUps(services, travel)
        travel_heads_ups.install()
    maintenance = Maintenance(services, tasks, services.calendar, scheduler)
    maintenance.install()
    routines = Routines(services)
    routines.install()
    habits = HabitReserve(services)
    habits.install()
    Reactions(services).install()
    WrongReplies(services).install()
    Commands(services).install()
    FeedbackChat(services).install()
    agent = Agent(services)
    channel.handler = agent
    if services.google is not None and google is not None:
        inbox = GoogleTasksInbox(services, services.google, google.tasks_url)
        inbox.task_list = GoogleTaskList(services, tasks)  # GT1b
        inbox.install(agent)
    periodic = [
        PeriodicTask("outbox.flush", timedelta(seconds=30), outbox.flush),
        PeriodicTask("approvals.resurface", timedelta(minutes=5), approvals.resurface),
        PeriodicTask("approvals.expire", timedelta(hours=1), approvals.expire),
        PeriodicTask("rules.expire_drafts", timedelta(hours=1), rulebook.expire_drafts),
        PeriodicTask("burnout.hand_over", timedelta(hours=1), burnout.hand_over),
        PeriodicTask("energy.expire_outcomes", timedelta(minutes=15), _async(outcomes.expire)),
        PeriodicTask("tasks.resurface", timedelta(minutes=15), tasks.resurface),
        PeriodicTask("tasks.schedules", timedelta(hours=1), tasks.check_schedules),
        PeriodicTask("tasks.day_end", timedelta(minutes=15), reminders.end_of_day),
        PeriodicTask("calendar.morning", timedelta(minutes=5), day_summary.morning),
        PeriodicTask("tasks.overdue", timedelta(hours=1), reminders.overdue),
        PeriodicTask("checkins.reviews", timedelta(minutes=15), reviews.run),
        PeriodicTask("habits.offer", timedelta(hours=6), habits.offer_due),
        PeriodicTask("habits.send", timedelta(hours=1), habits.send_due),
        PeriodicTask("pantry.predict", timedelta(hours=6), pantry.predict),
        PeriodicTask("safeway.expire", timedelta(minutes=5), safeway.expire_stale),
        PeriodicTask("memory.journal", timedelta(hours=1), journal.write),
        PeriodicTask("routines.check", timedelta(minutes=15), routines.check),
        PeriodicTask("maintenance.offer", timedelta(minutes=15), maintenance.offer),
    ]
    server = ServerControl(services, control_dir)
    server.install()
    if control_dir is not None:
        periodic.append(PeriodicTask("server.results", timedelta(minutes=1), server.check))
    if backup is not None:
        backups = BackupJob(store, Backups(backup, cipher), outbox)
        periodic.append(PeriodicTask("backup.nightly", timedelta(hours=1), backups.run))
    if grocery_list is not None:
        # Crossed off in the app: bought, and the pantry has it again, like the website's "Got it".
        mirror = GroceryMirror(
            db, grocery_list, bought=lambda name: pantry.set_status(name, "plenty", source="list")
        )
        periodic.append(PeriodicTask("groceries.mirror", timedelta(minutes=1), mirror.sync))
    if keep is not None:  # GK1, GK2: does nothing until someone runs `themi keep link`
        from_keep = KeepGroceries(
            db,
            KeepLinks(db, cipher),
            groceries,
            keep,
            bought=lambda name: pantry.set_status(name, "plenty", source="list"),
        )
        periodic.append(PeriodicTask("groceries.keep", timedelta(minutes=2), from_keep.sync))
    if cozyla is not None:
        family = store.get_family()
        cozyla.timezone = family.timezone if family else cozyla.timezone
    if cozyla is not None and cozyla.config.todo_list:
        wall = CozylaTodos(services, tasks, cozyla)
        wall.install()
        periodic.append(PeriodicTask("cozyla.sync", timedelta(minutes=1), wall.sync))
    if cozyla is not None and cozyla.config.chores:
        chart = CozylaChores(services, tasks, cozyla)
        chart.install()
        periodic.append(PeriodicTask("cozyla.chores", timedelta(minutes=5), chart.sync))
        wall_routines = CozylaRoutines(services, tasks, cozyla)
        wall_routines.install()
        periodic.append(PeriodicTask("cozyla.routines", timedelta(minutes=15), wall_routines.sync))
        mirror = RoutinesWall(services, routines, wall_routines, cozyla)
        mirror.install()
        periodic.append(PeriodicTask("routines.wall", timedelta(minutes=5), mirror.sync))
    if home_connect is not None:
        services.home_connect = HomeConnectAccount(db, cipher, home_connect)
        dishwasher = Dishwasher(services, tasks, services.home_connect)
        dishwasher.install()
        periodic.append(PeriodicTask("devices.dishwasher", timedelta(minutes=5), dishwasher.poll))
        periodic.append(
            PeriodicTask("devices.dishwasher_pace", timedelta(hours=1), dishwasher.pace)
        )
    if thinq is not None:
        account = ThinqAccount(db, cipher, thinq)
        services.thinq = ThinqWatcher(store, account, ThinqPush(account, thinq.mqtt))
        periodic.append(PeriodicTask("devices.thinq", timedelta(minutes=5), services.thinq.poll))
        periodic.append(
            PeriodicTask("devices.thinq_push", timedelta(minutes=1), services.thinq.listen)
        )
        laundry = Laundry(services, tasks, services.thinq)
        laundry.install()
        periodic.append(PeriodicTask("laundry.fresh", timedelta(minutes=15), laundry.check_fresh))
    if roborock is not None:
        services.roborock = RoborockWatcher(store, RoborockAccount(db, cipher, roborock))
        periodic.append(
            PeriodicTask("devices.vacuum", timedelta(minutes=1), services.roborock.poll)
        )
        vacuum = Vacuum(services, tasks, services.roborock)
        vacuum.install()
        periodic.append(PeriodicTask("vacuum.wall", timedelta(minutes=1), vacuum.onto_wall))
    if tuya is not None:
        services.tuya = TuyaWatcher(store, TuyaAccount(db, cipher, tuya))
        periodic.append(PeriodicTask("devices.feeders", timedelta(minutes=10), services.tuya.poll))
        Feeders(services, tasks, services.tuya).install()
    if catgenie is not None:
        services.catgenie = CatGenieWatcher(store, CatGenieAccount(db, cipher, catgenie))
        periodic.append(
            PeriodicTask("devices.litter_box", timedelta(minutes=10), services.catgenie.poll)
        )
        LitterBox(services, tasks, services.catgenie).install()
    Appliances(services).install()  # F20b: asked how they're doing, it reads them
    if services.google_tasks is not None:
        periodic.append(
            PeriodicTask("google_tasks.inbox", timedelta(minutes=1), services.google_tasks.run)
        )
    if services.gmail is not None:
        periodic.append(PeriodicTask("gmail.poll", timedelta(minutes=1), services.gmail.poll_all))
    if calendar_busy is not None:
        periodic.append(PeriodicTask("calendar.busy", timedelta(minutes=15), calendar_busy.refresh))
    if task_blocks is not None:
        periodic.append(PeriodicTask("blocks.tick", timedelta(minutes=5), task_blocks.tick))
    if travel_heads_ups is not None:
        periodic.append(
            PeriodicTask("travel.heads_up", timedelta(minutes=5), travel_heads_ups.heads_up)
        )
    if services.triage is not None:
        periodic.append(PeriodicTask("email.triage", timedelta(minutes=1), services.triage.run))
    if services.senders is not None:
        periodic.append(PeriodicTask("email.senders", timedelta(hours=6), services.senders.offer))
    if services.noise is not None:
        periodic.append(PeriodicTask("email.noise", timedelta(minutes=5), services.noise.run))
    if services.triage is not None:
        periodic.append(
            PeriodicTask("pantry.receipts", timedelta(minutes=10), pantry.read_pending_receipts)
        )
    if services.expected is not None:
        periodic.append(
            PeriodicTask("email.expected", timedelta(hours=1), services.expected.check_overdue)
        )
    if services.google is not None:
        periodic.append(
            PeriodicTask(
                "google.forget_states",
                timedelta(days=1),
                _async(services.google.oauth.forget_expired_states),
            )
        )
    return App(
        db,
        store,
        ai_settings,
        router,
        channel,
        outbox,
        services,
        agent,
        approvals,
        rulebook,
        periodic,
        scheduler,
        server,
    )


def _async(fn: Callable[[], object]) -> Callable[[], Awaitable[object]]:
    """Wrap a quick synchronous job so the scheduler can await it."""

    async def run() -> object:
        return fn()

    return run
