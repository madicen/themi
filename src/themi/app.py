"""Assemble Themi from its parts.

One function builds the whole object graph, so the CLI, the scenario
harness and `themi run` (prompt 10) all run the same wiring.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from themi.accounts import AccountStore
from themi.ai.retry import Sleep
from themi.ai.router import AIRouter, ProviderFactory
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy, ExecutorRegistry
from themi.backup import BackupConfig, Backups
from themi.backup.job import BackupJob
from themi.channels.calibration import PdaCalibrator
from themi.channels.outbox import Outbox
from themi.channels.pda import AIRewriter, PdaShield
from themi.channels.telegram import TelegramChannel
from themi.connectors.cozyla import CozylaClient
from themi.connectors.gcal import CalendarSync
from themi.connectors.gcal.busy import CalendarBusy
from themi.connectors.gmail import GmailSync, install_executors
from themi.connectors.google import GoogleAccounts, GoogleConfig, GoogleOAuth
from themi.connectors.ourgroceries import GroceryListClient, GroceryMirror
from themi.core.agent import Agent
from themi.core.approvals import ApprovalsUI
from themi.core.calendar import TaskCalendar
from themi.core.calls import VendorCalls
from themi.core.checkin_reviews import CheckinReviews
from themi.core.commands import Commands
from themi.core.cozyla_chores import CozylaChores
from themi.core.cozyla_routines import CozylaRoutines
from themi.core.cozyla_todos import CozylaTodos
from themi.core.expected import ExpectedEmails
from themi.core.feedback import FeedbackChat
from themi.core.groceries import GroceryList
from themi.core.habits import HabitReserve
from themi.core.lists import Lists
from themi.core.meals import Meals
from themi.core.memory import Memory
from themi.core.pantry import Pantry
from themi.core.reminders import Reminders
from themi.core.rules import Rulebook
from themi.core.services import Services
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.tasks import TaskBoard
from themi.core.tools import ToolRegistry
from themi.core.triage import EmailTriage
from themi.energy import EnergyModel
from themi.energy.matching import Matcher
from themi.energy.outcomes import OutcomeTracker
from themi.energy.windows import EnergyReceptivity
from themi.scheduler import Scheduler
from themi.storage.db import Database
from themi.storage.secrets import Cipher

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
    backup: BackupConfig | None = None,
) -> App:
    store = AccountStore(db, cipher)
    ai_settings = AISettingsStore(db, cipher)
    router = AIRouter(ai_settings, factory=provider_factory, sleep=sleep)
    channel = make_channel(store)
    energy = EnergyModel(store)
    outbox = Outbox(store, channel, PdaShield(AIRewriter(router)), EnergyReceptivity(energy))
    outcomes = OutcomeTracker(store)
    outbox.sent_listeners.append(outcomes.on_sent)
    services = Services(
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
    if google is not None:
        services.google = GoogleAccounts(store, GoogleOAuth(db, store.cipher, google))
        services.gmail = GmailSync(store, services.google, outbox)
        install_executors(services.autonomy.executors, services.gmail)
        EmailTriage(services, services.gmail).install()
        ExpectedEmails(services, services.gmail).install()
    groceries = GroceryList(services)
    groceries.install()
    Lists(services).install()
    pantry = Pantry(services, groceries)
    pantry.install()
    tasks = TaskBoard(services, Matcher(store, energy))
    tasks.install()
    reminders = Reminders(services, tasks)
    reminders.install()
    reviews = CheckinReviews(services)
    reviews.install()
    Meals(services, pantry).install()
    VendorCalls(services, tasks).install()
    scheduler = Scheduler(db)
    calendar_busy: CalendarBusy | None = None
    if services.google is not None:
        services.calendar = CalendarSync(store, services.google)
        TaskCalendar(services, tasks, services.calendar, scheduler).install()
        calendar_busy = CalendarBusy(store, services.calendar)
        outbox.calendar_blocks = calendar_busy.blocks
        energy.calendar_blocks = calendar_busy.blocks
    habits = HabitReserve(services)
    habits.install()
    Commands(services).install()
    FeedbackChat(services).install()
    agent = Agent(services)
    channel.handler = agent
    periodic = [
        PeriodicTask("outbox.flush", timedelta(seconds=30), outbox.flush),
        PeriodicTask("approvals.resurface", timedelta(minutes=5), approvals.resurface),
        PeriodicTask("approvals.expire", timedelta(hours=1), approvals.expire),
        PeriodicTask("rules.expire_drafts", timedelta(hours=1), rulebook.expire_drafts),
        PeriodicTask("energy.expire_outcomes", timedelta(minutes=15), _async(outcomes.expire)),
        PeriodicTask("tasks.resurface", timedelta(minutes=15), tasks.resurface),
        PeriodicTask("tasks.schedules", timedelta(hours=1), tasks.check_schedules),
        PeriodicTask("tasks.day_end", timedelta(minutes=15), reminders.end_of_day),
        PeriodicTask("tasks.overdue", timedelta(hours=1), reminders.overdue),
        PeriodicTask("checkins.reviews", timedelta(minutes=15), reviews.run),
        PeriodicTask("habits.offer", timedelta(hours=6), habits.offer_due),
        PeriodicTask("habits.send", timedelta(hours=1), habits.send_due),
        PeriodicTask("pantry.predict", timedelta(hours=6), pantry.predict),
    ]
    if backup is not None:
        backups = BackupJob(store, Backups(backup, cipher), outbox)
        periodic.append(PeriodicTask("backup.nightly", timedelta(hours=1), backups.run))
    if grocery_list is not None:
        # Crossed off in the app: bought, and the pantry has it again, like the website's "Got it".
        mirror = GroceryMirror(
            db, grocery_list, bought=lambda name: pantry.set_status(name, "plenty", source="list")
        )
        periodic.append(PeriodicTask("groceries.mirror", timedelta(minutes=1), mirror.sync))
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
        routines = CozylaRoutines(services, tasks, cozyla)
        routines.install()
        periodic.append(PeriodicTask("cozyla.routines", timedelta(minutes=15), routines.sync))
    if services.gmail is not None:
        periodic.append(PeriodicTask("gmail.poll", timedelta(minutes=1), services.gmail.poll_all))
    if calendar_busy is not None:
        periodic.append(PeriodicTask("calendar.busy", timedelta(minutes=15), calendar_busy.refresh))
    if services.triage is not None:
        periodic.append(PeriodicTask("email.triage", timedelta(minutes=1), services.triage.run))
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
    )


def _async(fn: Callable[[], object]) -> Callable[[], Awaitable[object]]:
    """Wrap a quick synchronous job so the scheduler can await it."""

    async def run() -> object:
        return fn()

    return run
