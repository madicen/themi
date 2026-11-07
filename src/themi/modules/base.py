"""The module contract's plain parts: the base class, setup steps, jobs and errors."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from themi.modules.context import ModuleContext
    from themi.settings import Settings


T = TypeVar("T")


class ModuleError(Exception):
    """A module list that can't be loaded: a missing requirement, a cycle, a name twice,
    or a service asked for that nobody provided. The message names the modules involved."""


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    every: timedelta
    run: Callable[[], Awaitable[object]]


@dataclass(frozen=True)
class SetupStep:
    """One question the setup wizard (CR11) asks for a module."""

    key: str  # the settings field it fills
    prompt: str  # what the wizard asks, in Themi's plain words
    secret: bool = False  # goes to .env, typed without echo, never into themi.toml
    help_url: str = ""  # where to get it (a key page, a console)


def as_job(fn: Callable[[], object]) -> Callable[[], Awaitable[object]]:
    """Wrap a quick synchronous job so the scheduler can await it."""

    async def run() -> object:
        return fn()

    return run


class ModuleSetup:
    """What a module is built from (CR5a): the app's settings, its own `[module.<name>]`
    section of themi.toml, and objects modules share (one Cozyla client for two modules)."""

    def __init__(
        self,
        settings: Settings,
        section: dict[str, object] | None = None,
        shared: dict[str, object] | None = None,
    ) -> None:
        self.settings = settings
        self.section = section or {}
        self._shared = {} if shared is None else shared

    def shared(self, key: str, make: Callable[[], T]) -> T:
        if key not in self._shared:
            self._shared[key] = make()
        return self._shared[key]  # type: ignore[return-value]


class Module:
    """Subclass and set `name`; override `install`. The class attributes are the module's
    declaration, read before anything is installed."""

    name: ClassVar[str] = ""
    requires: ClassVar[tuple[str, ...]] = ()
    optional: ClassVar[tuple[str, ...]] = ()  # ordered before this one when present
    settings: ClassVar[type[BaseModel] | None] = None  # CR5
    preferences: ClassVar[type[BaseModel] | None] = None  # CR7a
    migrations: ClassVar[str | None] = None  # CR6: a package folder of SQL files
    setup: ClassVar[tuple[SetupStep, ...]] = ()  # CR11

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        """This module as the settings set it up, or None when it isn't (a connector with
        no login). Modules that take nothing override nothing."""
        return cls()

    def install(self, ctx: ModuleContext) -> None:
        raise NotImplementedError(f"module {self.name or type(self).__name__} has no install")

    def __repr__(self) -> str:
        return f"<module {self.name}>"
