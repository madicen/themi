"""Assemble Themi from its parts.

One function builds the whole object graph, so the CLI, the scenario
harness and `themi run` (prompt 10) all run the same wiring.

CR2c: `build_app` builds the core, chooses the modules (`family_modules`), and loads
them in one call. The list's order is the order things install in, which is the order of
Telegram's command menu and of each hook list, so a module goes where its feature was.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
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
from themi.config import Template, load_template
from themi.connectors.catgenie import CatGenieConfig
from themi.connectors.cozyla import CozylaClient
from themi.connectors.gkeep import KeepFactory
from themi.connectors.google import GoogleConfig
from themi.connectors.homeconnect import HomeConnectClient
from themi.connectors.ourgroceries import GroceryListClient
from themi.connectors.recipe_page import PageReader
from themi.connectors.roborock import RoborockLogin
from themi.connectors.search import SearchBackend
from themi.connectors.spotify import SpotifyClient
from themi.connectors.thinq import ThinqConfig
from themi.connectors.travel import TravelClient
from themi.connectors.tuya import TuyaConfig
from themi.core.agent import Agent
from themi.core.appliances import AppliancesModule
from themi.core.approvals import ApprovalsUI
from themi.core.body_double import BodyDoubleModule
from themi.core.body_double_guided import GuidedStepsModule
from themi.core.body_double_modes import ModeChooserModule
from themi.core.body_double_music import MusicOffersModule
from themi.core.breaks import BreaksModule
from themi.core.burnout import BurnoutModule
from themi.core.business_hours import BusinessHoursModule
from themi.core.buying import BuyingModule
from themi.core.calls import CallsModule
from themi.core.checkin_reviews import CheckinReviewsModule
from themi.core.commands import CommandsModule
from themi.core.connector_modules import EmailAuditModule, GoogleTasksModule, TravelModule
from themi.core.conversation_mode import ConversationModeModule
from themi.core.cookbook_save import CookbookSaveModule
from themi.core.cooking import CookingModule
from themi.core.cooking_timers import CookingTimersModule
from themi.core.day_summary import DaySummaryModule
from themi.core.feedback import FeedbackModule
from themi.core.focus import FocusModule
from themi.core.follow_ups import FollowUpsModule
from themi.core.google_modules import CalendarModule, GmailModule, GoogleModule
from themi.core.groceries import GroceriesModule
from themi.core.guides import GuidesModule
from themi.core.habits import HabitsModule
from themi.core.home_modules import (
    CatGenieModule,
    CozylaChoresModule,
    CozylaTodosModule,
    HomeConnectModule,
    KeepModule,
    OurGroceriesModule,
    RoborockModule,
    SpotifyModule,
    ThinqModule,
    TuyaModule,
)
from themi.core.journal import JournalModule
from themi.core.liaison import LiaisonModule
from themi.core.lists import ListsModule
from themi.core.maintenance import MaintenanceModule
from themi.core.meals import MealsModule
from themi.core.memory import MemoryModule
from themi.core.pantry import PantryModule
from themi.core.prompts import CORE_RULES
from themi.core.reactions import ReactionsModule
from themi.core.recipe_groceries import RecipeGroceriesModule
from themi.core.recipe_ideas import RecipeIdeasModule
from themi.core.recipes import RecipesModule
from themi.core.reminders import RemindersModule
from themi.core.routines import RoutinesModule
from themi.core.routing import EmbeddingRouter
from themi.core.rules import Rulebook
from themi.core.safeway import SafewayModule
from themi.core.services import Services
from themi.core.spending import SpendingModule
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.step_images import StepPicturesModule
from themi.core.taking import TakingModule
from themi.core.tasks import TasksModule
from themi.core.tools import SETTINGS, ToolRegistry
from themi.core.web_recipes import WebRecipesModule
from themi.core.web_search import WebSearchModule
from themi.core.which_list import WhichListModule
from themi.core.which_task import TaskNamer
from themi.core.wrong_replies import WrongRepliesModule
from themi.energy import EnergyModel
from themi.energy.outcomes import OutcomeTracker
from themi.energy.windows import EnergyReceptivity
from themi.modules import Module, ModuleContext, PeriodicTask, as_job
from themi.scheduler import Scheduler
from themi.storage.db import Database
from themi.storage.secrets import Cipher
from themi.updates import ServerControl

ChannelFactory = Callable[[AccountStore], TelegramChannel]

__all__ = ["App", "ChannelFactory", "PeriodicTask", "build_app", "family_modules"]


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


def family_modules(
    *,
    google: GoogleConfig | None = None,
    grocery_list: GroceryListClient | None = None,
    cozyla: CozylaClient | None = None,
    travel: TravelClient | None = None,
    search: SearchBackend | None = None,
    recipe_pages: PageReader | None = None,
    home_connect: HomeConnectClient | None = None,
    spotify: SpotifyClient | None = None,
    thinq: ThinqConfig | None = None,
    roborock: RoborockLogin | None = None,
    tuya: TuyaConfig | None = None,
    catgenie: CatGenieConfig | None = None,
    keep: KeepFactory | None = None,
) -> list[Module]:
    """The family's modules, with each connector's only when it's set up. In install order
    (see the module docstring); CR5 turns this into the family template."""

    return [
        MemoryModule(),
        JournalModule(),
        *([GoogleModule(google), GmailModule()] if google else []),
        GroceriesModule(),
        SafewayModule(),
        ListsModule(),
        BuyingModule(),
        WhichListModule(),
        SpendingModule(),
        LiaisonModule(),
        BreaksModule(),
        PantryModule(),
        TasksModule(),
        FollowUpsModule(),
        *([EmailAuditModule()] if google else []),
        RemindersModule(),
        BusinessHoursModule(),  # F34k
        DaySummaryModule(),
        FocusModule(),
        TakingModule(),
        GuidesModule(),
        RecipesModule(google),  # RC1a: the cookbook doc
        CookbookSaveModule(),  # RC5
        RecipeGroceriesModule(),  # RC2a
        RecipeIdeasModule(),  # RC7
        CookingModule(),  # RC3a
        BurnoutModule(),
        ConversationModeModule(),
        CheckinReviewsModule(),
        MealsModule(),
        CallsModule(),
        CookingTimersModule(),  # RC3c: timers are scheduler jobs
        BodyDoubleModule(),  # BD1a: block ends are scheduler jobs
        GuidedStepsModule(),  # BD1b
        StepPicturesModule(),  # BD4b
        *([SpotifyModule(spotify)] if spotify else []),  # BD5b: their own music
        MusicOffersModule(),  # BD5c
        ModeChooserModule(),  # BD2
        *([CalendarModule()] if google else []),
        WebSearchModule(search),  # F30d: says how to set it up without a key
        WebRecipesModule(recipe_pages),  # RC4a: recipes from links
        *([TravelModule(travel)] if travel else []),
        MaintenanceModule(),
        RoutinesModule(),
        HabitsModule(),
        ReactionsModule(),
        WrongRepliesModule(),
        CommandsModule(),
        FeedbackModule(),
        *([GoogleTasksModule(google.tasks_url)] if google else []),
        *([OurGroceriesModule(grocery_list)] if grocery_list else []),
        *([KeepModule(keep)] if keep else []),
        *([CozylaTodosModule(cozyla)] if cozyla and cozyla.config.todo_list else []),
        *([CozylaChoresModule(cozyla)] if cozyla and cozyla.config.chores else []),
        *([HomeConnectModule(home_connect)] if home_connect else []),
        *([ThinqModule(thinq)] if thinq else []),
        *([RoborockModule(roborock)] if roborock else []),
        *([TuyaModule(tuya)] if tuya else []),
        *([CatGenieModule(catgenie)] if catgenie else []),
        AppliancesModule(),  # F20b: asked how they're doing, it reads them
    ]


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
    recipe_pages: PageReader | None = None,  # RC4a: tests and `make dev` point it at fakes
    home_connect: HomeConnectClient | None = None,
    spotify: SpotifyClient | None = None,  # BD5b
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
    modules: list[Module] | None = None,
    template: Template | None = None,
) -> App:
    """`modules`: the list to load instead of the family's (tests, and CR5's templates).
    `template`: the persona and prompt rewordings (CR8a); the family's when None."""
    template = template or load_template("family")
    if modules is None:
        modules = family_modules(
            google=google,
            grocery_list=grocery_list,
            cozyla=cozyla,
            travel=travel,
            search=search,
            recipe_pages=recipe_pages,
            home_connect=home_connect,
            spotify=spotify,
            thinq=thinq,
            roborock=roborock,
            tuya=tuya,
            catgenie=catgenie,
            keep=keep,
        )
    # ----- the core -------------------------------------------------------------------
    store = AccountStore(db, cipher)
    ai_settings = AISettingsStore(db, cipher)
    router = AIRouter(ai_settings, factory=provider_factory, sleep=sleep, hedge_after=hedge_after)
    channel = make_channel(store)
    energy = EnergyModel(store)
    outbox = Outbox(store, channel, PdaShield(AIRewriter(router)), EnergyReceptivity(energy))
    outcomes = OutcomeTracker(store)
    outbox.sent_listeners.append(outcomes.on_sent)
    tools = ToolRegistry(list(STARTER_TOOLS))
    tools.add_group(SETTINGS)  # CR8b: the core's own; modules add theirs
    services = Services(
        tool_routing=tool_routing,
        conversation_rollout=conversation_mode,
        group_router=EmbeddingRouter(RouterEmbedder(router), VectorCache(db), tools.examples),
        task_namer=TaskNamer(RouterEmbedder(router), VectorCache(db)),
        store=store,
        ai_settings=ai_settings,
        router=router,
        outbox=outbox,
        calibrator=PdaCalibrator(store),
        tools=tools,
        autonomy=Autonomy(store, ExecutorRegistry()),
        energy=energy,
        outcomes=outcomes,
        persona=template.persona,  # CR8a
        prompt_fragments=list(CORE_RULES),
        prompt_overrides=dict(template.prompt),
        role_modules={name: role.allowed() for name, role in template.roles.items()},  # CR9
    )
    scheduler = Scheduler(db)
    ctx = ModuleContext(services, scheduler=scheduler)
    approvals = ctx.provide(ApprovalsUI(services.autonomy, outbox))
    approvals.install(services)
    rulebook = ctx.provide(Rulebook(services.autonomy, outbox))
    rulebook.install(services)
    ctx.provide(energy)  # core, until the energy model becomes a module
    agent = ctx.provide(Agent(services))  # reads services per message, so it can come first
    channel.handler = agent
    ctx.periodic("outbox.flush", timedelta(seconds=30), outbox.flush)
    ctx.periodic("approvals.resurface", timedelta(minutes=5), approvals.resurface)
    ctx.periodic("approvals.expire", timedelta(hours=1), approvals.expire)
    ctx.periodic("rules.expire_drafts", timedelta(hours=1), rulebook.expire_drafts)
    ctx.periodic("energy.expire_outcomes", timedelta(minutes=15), as_job(outcomes.expire))

    # ----- the modules ----------------------------------------------------------------
    ctx.load(*modules)

    # ----- the core again: updates from the website, and backups -----------------------
    server = ServerControl(services, control_dir)
    server.install()
    if control_dir is not None:
        ctx.periodic("server.results", timedelta(minutes=1), server.check)
    if backup is not None:
        backups = BackupJob(store, Backups(backup, cipher), outbox)
        ctx.periodic("backup.nightly", timedelta(hours=1), backups.run)
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
        ctx.jobs,
        scheduler,
        server,
    )
