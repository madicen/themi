"""SP1: what happened to each module when Themi started.

A module's problem leaves that module off, and what needs it, and Themi starts anyway. The
report says which, in plain words, for the Modules page, the dashboard and
`themi config show`.

    on          built and installed
    off         removed in themi.toml, or it needs a module that isn't on
    not_set_up  its settings aren't there (a connector nobody has configured)
    failed      its settings are wrong, or building or installing it raised
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from themi import clock

ModuleState = Literal["on", "off", "not_set_up", "failed"]


@dataclass(frozen=True)
class ModuleStatus:
    name: str
    state: ModuleState
    kind: str = "feature"
    reason: str = ""  # why it isn't on, in plain words; empty when it is
    warn: bool = False  # said to admins although it isn't a failure (Telegram's missing token)


@dataclass
class StartReport:
    template: str = "family"
    made_at: datetime = field(default_factory=clock.now)
    modules: dict[str, ModuleStatus] = field(default_factory=dict)  # in the order considered
    # What `resolve_modules` (strict) stops on: the lines it always said.
    problems: list[str] = field(default_factory=list)
    ai_choices: tuple[str, ...] = ()  # the AI provider modules installed, for the warning

    def note(
        self, name: str, state: ModuleState, kind: str, reason: str = "", *, warn: bool = False
    ) -> None:
        self.modules[name] = ModuleStatus(name, state, kind, reason, warn)

    def state(self, name: str) -> ModuleState:
        status = self.modules.get(name)
        return status.state if status else "off"

    def on(self) -> list[str]:
        return [n for n, s in self.modules.items() if s.state == "on"]

    def failed(self) -> list[ModuleStatus]:
        return [s for s in self.modules.values() if s.state == "failed"]

    def has_ai(self) -> bool:
        return any(s.kind == "ai" and s.state == "on" for s in self.modules.values())

    def warnings(self) -> list[str]:
        """What an admin should hear about: no AI provider, and each module that failed."""
        out = []
        if not self.has_ai():
            choices = ", ".join(self.ai_choices) or "an AI provider module"
            out.append(f"Themi has no AI provider yet, so it can't answer. Add one of {choices}.")
        for status in self.modules.values():
            if status.state == "failed":
                out.append(f"{status.name} couldn't start: {status.reason}")
            elif status.warn:
                out.append(f"{status.name} isn't on: {status.reason}")
        return out

    def lines(self) -> list[str]:
        """For `themi config show`: each module that isn't on, and why."""
        words = {"off": "off", "not_set_up": "not set up", "failed": "couldn't start"}
        out = []
        for status in self.modules.values():
            if status.state == "on":
                continue
            reason = f": {status.reason}" if status.reason else ""
            out.append(f"  {status.name} ({words[status.state]}){reason}")
        return out
