"""CR10a: the home pack's modules that come with one outside service each (the wall,
the appliances, the grocery mirrors, Spotify). Split from connector_modules, which keeps
the ones the work template uses too (Google Tasks, the email audit, travel).

CR2c: the modules that come with one outside service each.

Each takes its connector's client or config in its constructor, and is in the module
list only when that service is set up. What the module's feature does lives in its own
file; this one only wires the connector to it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from themi.connectors.catgenie import CatGenieAccount, CatGenieConfig, CatGenieWatcher
from themi.connectors.cozyla import CozylaClient
from themi.connectors.gkeep import KeepFactory
from themi.connectors.homeconnect import HomeConnectAccount, HomeConnectClient
from themi.connectors.ourgroceries import GroceryListClient, GroceryMirror
from themi.connectors.roborock import RoborockAccount, RoborockLogin, RoborockWatcher
from themi.connectors.spotify import SpotifyClient, SpotifyLinks
from themi.connectors.thinq import ThinqAccount, ThinqConfig, ThinqPush, ThinqWatcher
from themi.connectors.tuya import TuyaAccount, TuyaConfig, TuyaWatcher
from themi.core import groups
from themi.core.chore_chart import ChartPreferences
from themi.core.connector_settings import (
    CozylaSettings,
    HomeConnectSettings,
    OurGroceriesSettings,
    SpotifySettings,
    ThinqSettings,
)
from themi.core.cozyla_chores import CozylaChores
from themi.core.cozyla_routines import CozylaRoutines
from themi.core.cozyla_todos import CozylaTodos
from themi.core.dishwasher import Dishwasher
from themi.core.feeders import Feeders
from themi.core.groceries import GroceryList
from themi.core.keep_groceries import KeepGroceries, KeepLinks
from themi.core.laundry import Laundry, LaundrySettings
from themi.core.litter_box import LitterBox
from themi.core.music import Music
from themi.core.pantry import Pantry
from themi.core.routines import Routines
from themi.core.routines_wall import RoutinesWall
from themi.core.tasks import TaskBoard
from themi.core.vacuum import Vacuum
from themi.modules import Module, ModuleContext, ModuleSetup
from themi.modules.prompt import PromptFragment


class SpotifyModule(Module):
    """BD5b: playing their own music, from Spotify."""

    name = "spotify"
    tool_groups = (groups.MUSIC,)
    settings = SpotifySettings

    def __init__(self, client: SpotifyClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        spotify = setup.read(SpotifySettings).config()
        return cls(SpotifyClient(spotify)) if spotify else None

    def install(self, ctx: ModuleContext) -> None:
        store = ctx.services.store
        links = SpotifyLinks(store.db, store.cipher, self.client)
        ctx.provide(Music(ctx.services, links)).install()


def _bought(ctx: ModuleContext) -> Callable[[str], object]:
    pantry = ctx.get(Pantry)
    # Crossed off in the app: bought, and the pantry has it again, like the website's "Got it".
    return lambda name: pantry.set_status(name, "plenty", source="list")


class OurGroceriesModule(Module):
    """The grocery list mirrored to OurGroceries."""

    name = "ourgroceries"
    settings = OurGroceriesSettings
    requires = ("groceries", "pantry")

    def __init__(self, client: GroceryListClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        from themi.connectors.ourgroceries import OurGroceriesClient

        grocery = setup.read(OurGroceriesSettings).config()
        return cls(OurGroceriesClient(grocery)) if grocery else None

    def install(self, ctx: ModuleContext) -> None:
        mirror = GroceryMirror(ctx.services.store.db, self.client, bought=_bought(ctx))
        ctx.periodic("groceries.mirror", timedelta(minutes=1), mirror.sync)


class KeepModule(Module):
    """GK1, GK2: groceries said to Google Home, from Google Keep. Does nothing until someone
    runs `themi keep link`."""

    name = "keep"
    requires = ("groceries", "pantry")

    def __init__(self, factory: KeepFactory) -> None:
        self.factory = factory

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        from themi.connectors.gkeep import GKeepAccount

        return cls(GKeepAccount)

    def install(self, ctx: ModuleContext) -> None:
        store = ctx.services.store
        from_keep = KeepGroceries(
            store.db,
            KeepLinks(store.db, store.cipher),
            ctx.get(GroceryList),
            self.factory,
            bought=_bought(ctx),
        )
        ctx.periodic("groceries.keep", timedelta(minutes=2), from_keep.sync)


def _wall(setup: ModuleSetup) -> CozylaClient | None:
    """One Cozyla client for both wall modules, as before (CR5a)."""
    config = setup.read(CozylaSettings).config()
    return setup.shared("cozyla", lambda: CozylaClient(config)) if config else None


def _wall_in_family_time(ctx: ModuleContext, cozyla: CozylaClient) -> None:
    family = ctx.services.store.get_family()
    cozyla.timezone = family.timezone if family else cozyla.timezone


class CozylaTodosModule(Module):
    """The Cozyla wall's to-do list, kept in step with Themi's tasks."""

    name = "cozyla_todos"
    tool_groups = (
        groups.LISTS,
        groups.WALL,
    )
    settings = CozylaSettings
    requires = ("tasks",)

    def __init__(self, client: CozylaClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        wall = _wall(setup)
        return cls(wall) if wall and wall.config.todo_list else None

    def install(self, ctx: ModuleContext) -> None:
        _wall_in_family_time(ctx, self.client)
        wall = ctx.provide(CozylaTodos(ctx.services, ctx.get(TaskBoard), self.client))
        wall.install()
        ctx.periodic("cozyla.sync", timedelta(minutes=1), wall.sync)


# CR8a: the system prompt's rules about this module's feature.
CHORE_PROMPT_RULES = (
    PromptFragment(
        "cozyla_chores.how-many-chores-someone",
        "act",
        110,
        """\
- How many chores someone sees on the wall's chore chart at once is a setting too
  (set_chore_chart_limit), not a rule; "a different one" or "another one" is
  change_chore_chart.""",
    ),
    PromptFragment(
        "cozyla_chores.an-item-for-someone",
        "act",
        130,
        """\
- An item for someone's morning, afternoon or evening routine on the wall is
  add_to_wall_routine: not a calendar event, a chore or a list.""",
    ),
)


class CozylaChoresModule(Module):
    """The Cozyla wall's chore chart and routines, and Themi's routines shown there."""

    name = "cozyla_chores"
    tool_groups = (groups.WALL,)
    preferences = ChartPreferences
    settings = CozylaSettings
    requires = ("tasks", "routines")

    def __init__(self, client: CozylaClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        wall = _wall(setup)
        return cls(wall) if wall and wall.config.chores else None

    def install(self, ctx: ModuleContext) -> None:
        ctx.prompt(*CHORE_PROMPT_RULES)
        ctx.settings_section("settings/chart.html", 50)
        _wall_in_family_time(ctx, self.client)
        s, tasks = ctx.services, ctx.get(TaskBoard)
        chart = ctx.provide(CozylaChores(s, tasks, self.client))
        chart.install()
        ctx.periodic("cozyla.chores", timedelta(minutes=5), chart.sync)
        wall_routines = ctx.provide(CozylaRoutines(s, tasks, self.client))
        wall_routines.install()
        ctx.periodic("cozyla.routines", timedelta(minutes=15), wall_routines.sync)
        mirror = ctx.provide(RoutinesWall(s, ctx.get(Routines), wall_routines, self.client))
        mirror.install()
        ctx.periodic("routines.wall", timedelta(minutes=5), mirror.sync)


class HomeConnectModule(Module):
    """H1: the dishwasher, through Home Connect."""

    name = "home_connect"
    settings = HomeConnectSettings
    requires = ("tasks",)

    def __init__(self, client: HomeConnectClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        config = setup.read(HomeConnectSettings).config()
        return cls(HomeConnectClient(config)) if config else None

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        account = HomeConnectAccount(s.store.db, s.store.cipher, self.client)
        ctx.provide(account)
        dishwasher = ctx.provide(Dishwasher(s, ctx.get(TaskBoard), account))
        dishwasher.install()
        ctx.periodic("devices.dishwasher", timedelta(minutes=5), dishwasher.poll)
        ctx.periodic("devices.dishwasher_pace", timedelta(hours=1), dishwasher.pace)


class ThinqModule(Module):
    """30: the washer and dryer, through LG ThinQ, and laundry that's waiting."""

    name = "thinq"
    household = LaundrySettings
    settings = ThinqSettings
    requires = ("tasks",)

    def __init__(self, config: ThinqConfig) -> None:
        self.config = config

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        import dataclasses

        from themi.connectors.thinq import mqtt

        thinq = setup.read(ThinqSettings).config()
        return cls(dataclasses.replace(thinq, mqtt=mqtt.available()))

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        account = ThinqAccount(s.store.db, s.store.cipher, self.config)
        watcher = ThinqWatcher(s.store, account, ThinqPush(account, self.config.mqtt))
        ctx.provide(watcher)
        ctx.periodic("devices.thinq", timedelta(minutes=5), watcher.poll)
        ctx.periodic("devices.thinq_push", timedelta(minutes=1), watcher.listen)
        laundry = ctx.provide(Laundry(s, ctx.get(TaskBoard), watcher))
        laundry.install()
        ctx.periodic("laundry.fresh", timedelta(minutes=15), laundry.check_fresh)


class RoborockModule(Module):
    """V1: the robot vacuum, through Roborock."""

    name = "roborock"
    requires = ("tasks",)

    def __init__(self, login: RoborockLogin) -> None:
        self.login = login

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        from themi.connectors.roborock import library

        login = library.available()  # the unofficial library, when it's installed
        return cls(login) if login else None

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        watcher = RoborockWatcher(s.store, RoborockAccount(s.store.db, s.store.cipher, self.login))
        ctx.provide(watcher)
        ctx.periodic("devices.vacuum", timedelta(minutes=1), watcher.poll)
        vacuum = ctx.provide(Vacuum(s, ctx.get(TaskBoard), watcher))
        vacuum.install()
        ctx.periodic("vacuum.wall", timedelta(minutes=1), vacuum.onto_wall)


class TuyaModule(Module):
    """32: the pet feeders, through Tuya's cloud."""

    name = "tuya"
    requires = ("tasks",)

    def __init__(self, config: TuyaConfig) -> None:
        self.config = config

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        return cls(TuyaConfig())

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        watcher = TuyaWatcher(s.store, TuyaAccount(s.store.db, s.store.cipher, self.config))
        ctx.provide(watcher)
        ctx.periodic("devices.feeders", timedelta(minutes=10), watcher.poll)
        ctx.provide(Feeders(s, ctx.get(TaskBoard), watcher)).install()


class CatGenieModule(Module):
    """CG1a: the litter box, through CatGenie's cloud."""

    name = "catgenie"
    requires = ("tasks",)

    def __init__(self, config: CatGenieConfig) -> None:
        self.config = config

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        return cls(CatGenieConfig())

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        account = CatGenieAccount(s.store.db, s.store.cipher, self.config)
        watcher = CatGenieWatcher(s.store, account)
        ctx.provide(watcher)
        ctx.periodic("devices.litter_box", timedelta(minutes=10), watcher.poll)
        ctx.provide(LitterBox(s, ctx.get(TaskBoard), watcher)).install()
