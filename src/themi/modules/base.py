"""The module contract's plain parts: the base class, setup steps, jobs and errors."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, TypeVar

from themi.accounts.household import HouseholdSettings
from themi.accounts.preferences import Preferences
from themi.modules.settings import ModuleSettings, read_settings

if TYPE_CHECKING:
    from themi.core.tools import ToolGroup
    from themi.modules.context import ModuleContext
    from themi.settings import Settings


T = TypeVar("T")


# CR19: what a module is, for `themi setup` (asked in this order) and the website.
# A channel is how people talk to Themi; an AI provider answers; a capability is something
# Themi can do with what it's sent (voice notes, pictures) or make (pictures); a connector
# brings an outside service; a feature is everything else.
ModuleKind = Literal["channel", "ai", "capability", "connector", "feature"]
KINDS: tuple[ModuleKind, ...] = ("channel", "ai", "capability", "connector", "feature")


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
    """What a module is built from (CR5a, CR5b): the app's core settings, the environment
    and themi.toml's module sections (for module settings), and objects modules share (one
    Cozyla client for two modules)."""

    def __init__(
        self,
        settings: Settings,
        section: dict[str, object] | None = None,
        shared: dict[str, object] | None = None,
        *,
        module: str = "",
        sections: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.settings = settings
        self.section = section or {}
        self._shared = {} if shared is None else shared
        self.module = module
        self.sections = sections or ({module: self.section} if module else {})

    def shared(self, key: str, make: Callable[[], T]) -> T:
        if key not in self._shared:
            self._shared[key] = make()
        return self._shared[key]  # type: ignore[return-value]

    def read[S: ModuleSettings](self, model: type[S], module: str = "") -> S:
        """A module's settings: this module's, or another's it builds on (Google's, for the
        cookbook). Raises SettingsProblem with lines for the person."""
        name = module or self.module
        key = f"settings:{name}:{model.__name__}"
        return self.shared(
            key,
            lambda: read_settings(
                model, self.settings.environment, self.sections.get(name, {}), name
            ),
        )


class Module:
    """Subclass and set `name`; override `install`. The class attributes are the module's
    declaration, read before anything is installed."""

    name: ClassVar[str] = ""
    kind: ClassVar[ModuleKind] = "feature"  # CR19
    requires: ClassVar[tuple[str, ...]] = ()
    optional: ClassVar[tuple[str, ...]] = ()  # ordered before this one when present
    settings: ClassVar[type[ModuleSettings] | None] = None  # CR5b: from env and themi.toml
    preferences: ClassVar[type[Preferences] | None] = None  # CR7a: per member
    household: ClassVar[type[HouseholdSettings] | None] = None  # CR7c: per household
    # CR6: its own migration track: a package of NNNN_name.sql files, or a folder.
    migrations: ClassVar[str | Path | None] = None
    setup: ClassVar[tuple[SetupStep, ...]] = ()  # CR11
    tool_groups: ClassVar[tuple[ToolGroup, ...]] = ()  # CR8b: the groups its tools are in
    website: ClassVar[str] = ""  # CR11: what's left to do on the website once it's set up

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        """This module as the settings set it up, or None when it isn't (a connector with
        no login). Modules that take nothing override nothing."""
        return cls()

    async def check(self) -> str | None:
        """CR11: try the module's settings against its service, through its own client:
        None when they work, else what's wrong, in plain words. Most have nothing to try."""
        return None

    def install(self, ctx: ModuleContext) -> None:
        raise NotImplementedError(f"module {self.name or type(self).__name__} has no install")

    def __repr__(self) -> str:
        return f"<module {self.name}>"
