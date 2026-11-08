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
from typing import Any

from themi.accounts import AccountStore
from themi.ai.embeddings import RouterEmbedder, VectorCache
from themi.ai.retry import Sleep
from themi.ai.router import HEDGE_AFTER, AIRouter, ProviderFactory, module_factory
from themi.ai.settings import AISettingsStore
from themi.autonomy import Autonomy, ExecutorRegistry
from themi.backup import BackupConfig, Backups
from themi.backup.job import BackupJob
from themi.channels.base import Channel
from themi.channels.calibration import PdaCalibrator
from themi.channels.channel_set import ChannelSet
from themi.channels.outbox import Outbox
from themi.channels.pda import AIRewriter, PdaShield
from themi.config import Template, load_template
from themi.connectors.search import SearchBackend
from themi.connectors.travel import TravelClient
from themi.core.agent import Agent
from themi.core.approvals import ApprovalsUI
from themi.core.prompts import CORE_RULES
from themi.core.routing import EmbeddingRouter
from themi.core.rules import Rulebook
from themi.core.services import Services
from themi.core.starter_tools import STARTER_TOOLS
from themi.core.tools import SETTINGS, ToolRegistry
from themi.core.which_task import TaskNamer
from themi.energy import EnergyModel
from themi.energy.outcomes import OutcomeTracker
from themi.energy.windows import EnergyReceptivity
from themi.modules import Module, ModuleContext, PeriodicTask, as_job
from themi.scheduler import Scheduler
from themi.standard.ai_providers import AI_PROVIDERS
from themi.standard.breaks import BreaksModule
from themi.standard.burnout import BurnoutModule
from themi.standard.business_hours import BusinessHoursModule
from themi.standard.capabilities import ImageGenerationModule, PicturesModule, VoiceNotesModule
from themi.standard.checkin_reviews import CheckinReviewsModule
from themi.standard.commands import CommandsModule
from themi.standard.conversation_mode import ConversationModeModule
from themi.standard.day_summary import DaySummaryModule
from themi.standard.feedback import FeedbackModule
from themi.standard.focus import FocusModule
from themi.standard.follow_ups import FollowUpsModule
from themi.standard.guides import GuidesModule
from themi.standard.habits import HabitsModule
from themi.standard.journal import JournalModule
from themi.standard.lists import ListsModule
from themi.standard.memory import MemoryModule
from themi.standard.reactions import ReactionsModule
from themi.standard.reminders import RemindersModule
from themi.standard.routines import RoutinesModule
from themi.standard.taking import TakingModule
from themi.standard.tasks import TasksModule
from themi.standard.telegram import TelegramModule
from themi.standard.web_search import WebSearchModule
from themi.standard.wrong_replies import WrongRepliesModule
from themi.storage.db import Database
from themi.storage.secrets import Cipher
from themi.updates import ServerControl
from themi_google.connector_modules import EmailAuditModule, GoogleTasksModule, TravelModule
from themi_google.connectors.google import GoogleConfig
from themi_google.google_modules import (
    CalendarBusyModule,
    CalendarCopiesModule,
    CalendarModule,
    CalendarTwinsModule,
    EmailForwardingModule,
    EmailTriageModule,
    ExpectedEmailsModule,
    GmailModule,
    GoogleModule,
    NoiseDigestModule,
    TaskBlocksModule,
    UrgentSendersModule,
)
from themi_home.appliances import AppliancesModule
from themi_home.body_double import BodyDoubleModule
from themi_home.body_double_guided import GuidedStepsModule
from themi_home.body_double_modes import ModeChooserModule
from themi_home.body_double_music import MusicOffersModule
from themi_home.buying import BuyingModule
from themi_home.calls import CallsModule
from themi_home.chore_chart import ChoreChartModule
from themi_home.connectors.catgenie import CatGenieConfig
from themi_home.connectors.cozyla import CozylaClient
from themi_home.connectors.gkeep import KeepFactory
from themi_home.connectors.homeconnect import HomeConnectClient
from themi_home.connectors.ourgroceries import GroceryListClient
from themi_home.connectors.recipe_page import PageReader
from themi_home.connectors.roborock import RoborockLogin
from themi_home.connectors.spotify import SpotifyClient
from themi_home.connectors.thinq import ThinqConfig
from themi_home.connectors.tuya import TuyaConfig
from themi_home.cookbook_save import CookbookSaveModule
from themi_home.cooking import CookingModule
from themi_home.cooking_timers import CookingTimersModule
from themi_home.groceries import GroceriesModule
from themi_home.home_modules import (
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
from themi_home.liaison import LiaisonModule
from themi_home.maintenance import MaintenanceModule
from themi_home.meals import MealsModule
from themi_home.pantry import PantryModule
from themi_home.recipe_groceries import RecipeGroceriesModule
from themi_home.recipe_ideas import RecipeIdeasModule
from themi_home.recipes import RecipesModule
from themi_home.safeway import SafewayModule
from themi_home.spending import SpendingModule
from themi_home.step_images import StepPicturesModule
from themi_home.web_recipes import WebRecipesModule
from themi_home.which_list import WhichListModule

ChannelFactory = Callable[[AccountStore], Channel]  # CR20a1: any channel

__all__ = ["App", "ChannelFactory", "PeriodicTask", "build_app", "family_modules"]


@dataclass
class App:
    db: Database
    store: AccountStore
    ai_settings: AISettingsStore
    router: AIRouter
    channel: ChannelSet  # CR20b: every channel, as one
    outbox: Outbox
    services: Services
    agent: Agent
    approvals: ApprovalsUI
    rulebook: Rulebook
    periodic: list[PeriodicTask] = field(default_factory=list)
    # Queued background work (the Runtime adds the periodic tasks to it too).
    scheduler: Scheduler | None = None
    server: ServerControl | None = None  # updates and restarts from the website (D3a)
    modules: list[Module] = field(default_factory=list)  # CR16: what was loaded, in order


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
        TelegramModule(),  # CR20b: the channel (the runner's, added before modules install)
        *(provider() for provider in AI_PROVIDERS),  # CR19: every provider and capability
        VoiceNotesModule(),
        PicturesModule(),
        ImageGenerationModule(),
        MemoryModule(),
        JournalModule(),
        *(
            [
                GoogleModule(google),
                GmailModule(),
                EmailTriageModule(),  # CR18b: Gmail's features, each its own module
                EmailForwardingModule(),
                UrgentSendersModule(),
                ExpectedEmailsModule(),
                NoiseDigestModule(),
            ]
            if google
            else []
        ),
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
        ChoreChartModule(),  # CR21a: the chart, with or without the wall
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
        *(
            [
                CalendarModule(),
                CalendarBusyModule(),  # CR18b: the calendar's features, each its own module
                CalendarTwinsModule(),
                CalendarCopiesModule(),
                TaskBlocksModule(),
            ]
            if google
            else []
        ),
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
    make_channel: ChannelFactory | None,
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
    # CR19: backends are built with the loaded AI provider modules' adapters.
    adapters: dict[str, Any] = {}
    router = AIRouter(
        ai_settings,
        factory=provider_factory or module_factory(adapters),
        sleep=sleep,
        hedge_after=hedge_after,
    )
    # CR20b: the channels, as one for the core. A factory given here is Telegram's (the
    # runner's and the tests'); channel modules add theirs as they install.
    channel = ChannelSet()
    if make_channel is not None:
        channel.add("telegram", make_channel(store))
    energy = EnergyModel(store)
    outbox = Outbox(store, channel, PdaShield(AIRewriter(router)), EnergyReceptivity(energy))
    outcomes = OutcomeTracker(store)
    outbox.sent_listeners.append(outcomes.on_sent)
    tools = ToolRegistry(list(STARTER_TOOLS))
    tools.add_group(SETTINGS)  # CR8b: the core's own; modules add theirs
    tools.reword(template.tools, template.groups)  # CR12: the template's own words
    services = Services(
        tool_routing=tool_routing,
        conversation_rollout=conversation_mode,
        group_router=EmbeddingRouter(RouterEmbedder(router), VectorCache(db), tools.examples),
        task_namer=TaskNamer(RouterEmbedder(router), VectorCache(db)),
        store=store,
        ai_settings=ai_settings,
        ai_adapters=adapters,
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
        channels=channel,
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
    loaded = ctx.load(*modules)

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
        modules=loaded,
    )
