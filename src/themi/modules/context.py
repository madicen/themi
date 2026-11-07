"""`ModuleContext`: the one door a module has into the app.

It hands a module the core services and collects what the module adds. In CR1 most
registrations forward to `Services`, so modules and features not yet moved (CR2) live
side by side. CR3 moves the features' slots on `Services` onto `provide`/`get`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, TypeVar

from themi.modules.base import Module, ModuleError, PeriodicTask
from themi.modules.loader import order
from themi.modules.registry import Key, name_of
from themi.modules.web import MenuEntry, WebPages
from themi.storage.migrations import apply_track

if TYPE_CHECKING:
    from fastapi import APIRouter

    from themi.accounts import Member
    from themi.accounts.preferences import Preferences
    from themi.autonomy.engine import Executor
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
    from themi.modules.prompt import PromptFragment
    from themi.scheduler import Scheduler
    from themi.web.kit import Kit

T = TypeVar("T")


class ModuleContext:
    def __init__(self, services: Services, *, scheduler: Scheduler | None = None) -> None:
        self.services = services
        self._scheduler = scheduler
        self.installed: list[str] = []
        self.jobs: list[PeriodicTask] = []
        self._providers: dict[str, str] = {}  # class name -> the module that provided it
        self._current = ""  # the module installing now, for error messages

    # ----- loading --------------------------------------------------------------------

    def load(self, *modules: Module) -> list[Module]:
        """Install these modules in dependency order. Can be called more than once; a later
        call's modules may require ones installed earlier."""
        ordered = order(modules, self.installed)
        for module in ordered:
            self._current = module.name
            try:
                if module.migrations is not None:  # CR6: its tables, before it installs
                    apply_track(self.services.store.db, module.name, module.migrations)
                if module.preferences is not None:  # CR7a: for the settings page
                    self.services.preference_models.append(module.preferences)
                if module.household is not None:  # CR7c: for the family's pages
                    self.services.household_models.append(module.household)
                module.install(self)
            finally:
                self._current = ""
            self.installed.append(module.name)
        return ordered

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
        self.jobs.append(PeriodicTask(name, every, run))

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

    def settings_section(self, template: str, order: int) -> None:
        """CR7d: a section of the settings form (a template under the site's templates),
        placed among the core's by `order` (quiet hours 10 ... what Themi notices 100)."""
        self.services.settings_sections.append((order, template))

    def web(self, routes: Callable[[Kit], APIRouter], *menu: MenuEntry) -> None:
        """CR4: the module's website pages, and where they go in the menu."""
        self.services.web_pages.append(WebPages(routes, menu))

    def executor(self, name: str, fn: Executor) -> None:
        self.services.autonomy.executors.register(name)(fn)

    def _who(self) -> str:
        return f"module {self._current}" if self._current else "the app"
