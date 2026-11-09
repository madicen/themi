"""`ModuleContext`: the one door a module has into the app.

It hands a module the core services and collects what the module adds. In CR1 most
registrations forward to `Services`, so modules and features not yet moved (CR2) live
side by side. CR3 moves the features' slots on `Services` onto `provide`/`get`.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from themi.modules.base import Module, ModuleError, PeriodicTask
from themi.modules.loader import order
from themi.modules.registry import Key, name_of
from themi.modules.web import AccountsSection, MenuEntry, Panel, Values, Waiting, WebPages
from themi.storage.migrations import apply_track

if TYPE_CHECKING:
    from fastapi import APIRouter

    from themi.accounts import Member
    from themi.accounts.preferences import Preferences
    from themi.ai.router import ProviderFactory
    from themi.autonomy.engine import Executor
    from themi.channels.base import Channel
    from themi.core.services import (
        AwaitingSource,
        CommandHandler,
        EventCommandHandler,
        EventHandler,
        OpenItemSource,
        Services,
        TextHandler,
    )
    from themi.core.tools import Tool
    from themi.modules.mirrors import Mirror
    from themi.modules.prompt import PromptFragment
    from themi.scheduler import Scheduler
    from themi.web.kit import Kit

T = TypeVar("T")
log = logging.getLogger(__name__)


class ModuleContext:
    def __init__(self, services: Services, *, scheduler: Scheduler | None = None) -> None:
        self.services = services
        self._scheduler = scheduler
        self.installed: list[str] = []
        self.modules: list[Module] = []  # CR18a: the installed modules themselves
        self.jobs: list[PeriodicTask] = []
        self._providers: dict[str, str] = {}  # class name -> the module that provided it
        self._current = ""  # the module installing now, for error messages
        # SP1: modules a tolerant load left out, with why (an install raised, or it needs
        # one that did)
        self.failed: dict[str, str] = {}

    # ----- loading --------------------------------------------------------------------

    def load(self, *modules: Module, tolerant: bool = False) -> list[Module]:
        """Install these modules in dependency order. Can be called more than once; a later
        call's modules may require ones installed earlier.

        SP1: `tolerant`, and a module whose install raises is left out, with what needs
        it: what it had added is taken back (`_Snapshot`), the reason goes in `failed`,
        and the rest install. Otherwise the error goes up, as before."""
        ordered = order(modules, self.installed)
        done: list[Module] = []
        for module in ordered:
            missing = [r for r in module.requires if r in self.failed]
            if missing:
                self.failed[module.name] = f"it needs {', '.join(missing)}, which couldn't start"
                continue
            snapshot = _Snapshot(self) if tolerant else None
            self._current = module.name
            try:
                self._install(module)
            except Exception as exc:
                if snapshot is None:
                    raise
                snapshot.restore()
                self.failed[module.name] = f"it couldn't start: {exc}"
                log.warning("Module %s couldn't start; left out", module.name, exc_info=True)
                continue
            finally:
                self._current = ""
                self.services.tools.installing = ""
            self.installed.append(module.name)
            self.modules.append(module)
            done.append(module)
        return done

    def _install(self, module: Module) -> None:
        for group in module.tool_groups:  # CR8b: the groups its tools are in
            self.services.tools.add_group(group)
        if module.migrations is not None:  # CR6: its tables, before it installs
            apply_track(self.services.store.db, module.name, module.migrations)
        if module.preferences is not None:  # CR7a: for the settings page
            self.services.preference_models.append(module.preferences)
        if module.household is not None:  # CR7c: for the family's pages
            self.services.household_models.append(module.household)
        self._web_folder(module)
        self.services.tools.installing = module.name  # CR9: whose tools these are
        module.install(self)

    def _web_folder(self, module: Module) -> None:
        """CR17b: a module from a pack brings the pack's `web` folder (its page templates
        and static files), found next to the pack's package. The core's own is the site's."""
        package = type(module).__module__.split(".")[0]
        if package == "themi":
            return
        name = package.removeprefix("themi_")
        if name in self.services.web_folders:
            return
        root = sys.modules[package].__file__
        folder = Path(root).parent / "web" if root else None
        if folder is not None and folder.is_dir():
            self.services.web_folders[name] = folder

    def has(self, name: str) -> bool:
        return name in self.installed

    # ----- services between modules ---------------------------------------------------

    def provide(self, obj: T) -> T:
        """Make `obj` findable by its class (`get(type(obj))`, or a key naming the class),
        in the services registry. Returns it, for chaining."""
        kind = type(obj)
        found = self.services.maybe(kind)
        if found is not None and found is not obj:
            first = self._providers.get(kind.__name__) or "the core"
            raise ModuleError(f"{kind.__name__} is provided twice ({first} and {self._who()})")
        self.services.provide(kind, obj)
        self._providers[kind.__name__] = self._current
        return obj

    def get(self, kind: type[T] | Key[T]) -> T:
        found = self.maybe(kind)
        if found is None:
            raise ModuleError(
                f"{self._who()} asked for {name_of(kind)}, which no installed module provides"
            )
        return found

    def maybe(self, kind: type[T] | Key[T]) -> T | None:
        return self.services.maybe(kind)  # type: ignore[arg-type]

    @property
    def scheduler(self) -> Scheduler:
        if self._scheduler is None:
            raise ModuleError(f"{self._who()} needs the scheduler, and this app has none")
        return self._scheduler

    # ----- what a module adds ----------------------------------------------------------

    def periodic(self, name: str, every: timedelta, run: Callable[[], Awaitable[object]]) -> None:
        if any(job.name == name for job in self.jobs):
            raise ModuleError(f"periodic job {name} is added twice (last by {self._who()})")
        if self._current:  # a module's: it waits for the family (the core's never do)
            run = self._once_claimed(run)
        self.jobs.append(PeriodicTask(name, every, run))

    def _once_claimed(
        self, run: Callable[[], Awaitable[object]]
    ) -> Callable[[], Awaitable[object]]:
        """A module's job does nothing until there's a family. Before the claim (SP7a)
        there's nobody for it to act for, though .env can already have turned it on."""
        store = self.services.store
        claimed = False

        async def job() -> object:
            nonlocal claimed
            if not claimed:
                claimed = store.get_family() is not None
                if not claimed:
                    return None
            return await run()

        return job

    def tool(self, t: Tool) -> None:
        self.services.tools.register(t)

    def command(self, name: str, handler: CommandHandler, description: str) -> None:
        self.services.add_command(name, handler, description)

    def event_command(self, name: str, handler: EventCommandHandler, description: str) -> None:
        self.services.add_event_command(name, handler, description)

    def button(self, prefix: str, handler: EventHandler) -> None:
        if prefix in self.services.button_handlers:
            raise ModuleError(f"button prefix {prefix} is taken (asked by {self._who()})")
        self.services.button_handlers[prefix] = handler

    def reaction(self, handler: EventHandler) -> None:
        self.services.reaction_handlers.append(handler)

    def text_handler(self, handler: TextHandler) -> None:
        self.services.text_handlers.append(handler)

    def awaiting_source(self, source: AwaitingSource) -> None:
        self.services.awaiting_sources.append(source)

    def open_item_source(self, source: OpenItemSource) -> None:
        self.services.open_item_sources.append(source)

    def preferences[P: Preferences](self, member: Member, model: type[P]) -> P:
        """CR7a: a member's preferences for a module (the store holds them)."""
        return self.services.store.preferences(member.id, model)

    def prompt(self, *fragments: PromptFragment) -> None:
        """CR8a: rules for the system prompt about this module's feature."""
        self.services.prompt_fragments.extend(fragments)

    def settings_section(
        self,
        template: str,
        order: int,
        *,
        values: Callable[[Member], dict[str, object]] | None = None,
        save: Callable[[Member, object], None] | None = None,
    ) -> None:
        """CR7d: a section of the settings form (a template under the site's templates),
        placed among the core's by `order` (quiet hours 10 ... what Themi notices 100).
        CR10a: `values` adds to what the page shows; `save` takes the form after the
        preferences are saved, for what isn't a preference."""
        self.services.settings_sections.append((order, template))
        if values is not None:
            self.services.settings_values.append(values)
        if save is not None:
            self.services.settings_savers.append(save)

    def web(self, routes: Callable[[Kit], APIRouter], *menu: MenuEntry) -> None:
        """CR4: the module's website pages, and where they go in the menu."""
        self.services.web_pages.append(WebPages(routes, menu))

    def dashboard_panel(self, template: str, order: int, *, values: Values | None = None) -> None:
        """CR17a: a panel on the dashboard, placed among the modules' by `order` (tasks 20,
        around the house 30, the grocery list 40), between "Waiting on you" and "Recently"."""
        self.services.dashboard_panels.append(Panel(order, template, values))

    def accounts_section(
        self,
        template: str,
        order: int,
        *,
        values: Values | None = None,
        routes: Callable[[Kit], APIRouter] | None = None,
        household: bool = False,
    ) -> None:
        """CR17a: a part of the Accounts page and the routes its forms post to. A member's
        own sections come first by `order`; `household` rows go under "Household
        connections", for admins only. A section whose `values` gives None isn't shown."""
        self.services.accounts_sections.append(AccountsSection(order, template, values, household))
        if routes is not None:
            self.web(routes)

    def waiting_link(self, link: Waiting) -> None:
        """CR17a: a line in "Waiting on you" standing for some waiting actions."""
        self.services.waiting_links.append(link)

    def ai_adapter(self, kind: str, builder: ProviderFactory) -> None:
        """CR19: an AI provider module's adapter for one kind of backend; the router builds
        a member's backends of that kind with it."""
        self.services.ai_adapters[kind] = builder

    def channel(self, name: str, channel: Channel) -> None:
        """CR20b: a channel people talk to Themi on ("telegram", "web_chat")."""
        self.services.channels.add(name, channel)

    def mirror(self, mirror: Mirror) -> None:
        """CR21b: a display or app keeping lists, tasks or routines in step."""
        self.services.mirrors.add(mirror)

    def capability(self, name: str) -> None:
        """CR19: something Themi can now do ("voice_notes", "pictures", "image_generation")."""
        self.services.capabilities.add(name)

    def executor(self, name: str, fn: Executor) -> None:
        self.services.autonomy.executors.register(name)(fn)

    def _who(self) -> str:
        return f"module {self._current}" if self._current else "the app"


class _Snapshot:
    """SP1: what a module's install could change, as it was before, so a failed install can
    be taken back: every list, dict and set on the services and on the registries modules
    add to (tools, channels, executors, mirrors), the context's jobs, and the services'
    other attributes. Only what lives in those is taken back; a module that changed
    something else before raising leaves that changed. Its migrations stay applied (its
    tables are harmless without it)."""

    def __init__(self, ctx: ModuleContext) -> None:
        services = ctx.services
        self._objects: list[tuple[object, dict[str, object], dict[str, object]]] = []
        targets = [
            ctx,
            services,
            services.tools,
            services.channels,
            services.mirrors,
            getattr(services.autonomy, "executors", None),
        ]
        for target in targets:
            if target is None:
                continue
            attrs = dict(vars(target))
            copies = {k: _copy(v) for k, v in attrs.items() if isinstance(v, (list, dict, set))}
            self._objects.append((target, attrs, copies))

    def restore(self) -> None:
        for target, attrs, copies in self._objects:
            now = vars(target)
            for name in [n for n in now if n not in attrs]:
                delattr(target, name)
            for name, value in attrs.items():
                if name in copies:  # the same container, its old contents
                    _refill(value, copies[name])
                elif now.get(name) is not value:
                    setattr(target, name, value)


def _copy(value: object) -> object:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return set(value)  # type: ignore[arg-type]


def _refill(container: object, old: object) -> None:
    if isinstance(container, list) and isinstance(old, list):
        container[:] = old
    elif isinstance(container, (dict, set)) and isinstance(old, (dict, set)):
        container.clear()
        container.update(old)  # type: ignore[arg-type]
