"""SP5: what a change on the Modules page means, before it's made.

The draft says which modules are turned on or off relative to the template (or, when it
switches template, relative to the new one). From it and the current config:

- `desired`: the modules this Themi will have after a restart, in order;
- `turn_on`: a module and what it needs that isn't there yet;
- `turn_off`: a module and everything that needs it;
- `switch_template`: what a new template turns off (and what each takes with it) and on;
- `as_config`: the config the draft makes, for SP6 to write.

Nothing here touches the database: the page asks, shows, and only then saves the draft.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from themi.modules.base import Module
from themi.modules.store import Draft

if TYPE_CHECKING:
    from themi.config import InstanceConfig

Templates = Callable[[str], tuple[str, ...]]  # a template's name -> its modules


@dataclass(frozen=True)
class Change:
    """What one switch would do: the modules turned on (the one asked for last) or off (the
    one asked for first)."""

    on: tuple[str, ...] = ()
    off: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateSwitch:
    template: str
    off: tuple[tuple[str, tuple[str, ...]], ...] = ()  # each turned off, and what goes with it
    on: tuple[str, ...] = ()


@dataclass
class Planner:
    config: InstanceConfig
    known: dict[str, type[Module]]
    template_modules: Templates
    draft: Draft = field(default_factory=Draft)

    # ----- what the Themi will be -------------------------------------------------------

    @property
    def template(self) -> str:
        return self.draft.template or self.config.template

    def base(self) -> list[str]:
        """The modules before the draft's switches: the new template's whole, or the
        current template with themi.toml's changes."""
        if self.draft.template:
            return list(self.template_modules(self.draft.template))
        names = [
            n for n in self.template_modules(self.config.template) if n not in self.config.removed
        ]
        return names + [n for n in self.config.added if n not in names]

    def desired(self) -> list[str]:
        names = [n for n in self.base() if self.draft.modules.get(n, True)]
        return names + [n for n, on in self.draft.modules.items() if on and n not in names]

    # ----- dependencies -------------------------------------------------------------------

    def needs(self, name: str) -> list[str]:
        """Everything `name` requires, deepest first."""
        out: list[str] = []

        def visit(n: str) -> None:
            for need in self.known[n].requires if n in self.known else ():
                if need not in out:
                    visit(need)
                    out.append(need)

        visit(name)
        return out

    def needed_by(self, name: str, among: Iterable[str]) -> list[str]:
        """The modules in `among` that need `name`, directly or through another."""
        among = list(among)
        return [n for n in among if n != name and name in self.needs(n)]

    # ----- changes ------------------------------------------------------------------------

    def turn_on(self, name: str) -> Change:
        desired = set(self.desired())
        return Change(on=tuple(n for n in (*self.needs(name), name) if n not in desired))

    def turn_off(self, name: str) -> Change:
        desired = self.desired()
        if name not in desired:
            return Change()
        return Change(off=(name, *self.needed_by(name, desired)))

    def apply(self, change: Change) -> None:
        """Put a change in the draft. A switch back to how the base has it is dropped, so
        turning something on and off again leaves no change."""
        base = set(self.base())
        for name in change.on:
            self._set(name, True, base)
        for name in change.off:
            self._set(name, False, base)

    def _set(self, name: str, on: bool, base: set[str]) -> None:
        if (name in base) == on:
            self.draft.modules.pop(name, None)
        else:
            self.draft.modules[name] = on

    def switch_template(self, template: str) -> TemplateSwitch:
        """What changing to `template` would do (nothing is changed)."""
        now = self.desired()
        after = list(self.template_modules(template))
        gone = [n for n in now if n not in after]
        # each module that goes on its own account, with what goes because it needs it
        roots = [n for n in gone if not any(g in self.needs(n) for g in gone)]
        off = tuple((n, tuple(self.needed_by(n, gone))) for n in roots)
        return TemplateSwitch(template, off, tuple(n for n in after if n not in now))

    def use_template(self, template: str) -> None:
        """Put the switch in the draft: the new template whole, the switches gone."""
        self.draft.template = None if template == self.config.template else template
        self.draft.modules.clear()

    # ----- the result -------------------------------------------------------------------

    def as_config(self) -> InstanceConfig:
        """The config this draft makes (its secrets are applied separately, in SP6)."""
        template = list(self.template_modules(self.template))
        desired = self.desired()
        sections = {name: dict(values) for name, values in self.config.sections.items()}
        for name, values in self.draft.sections.items():
            merged = sections.setdefault(name, {})
            for key, value in values.items():
                if value is None or value == "":
                    merged.pop(key, None)
                else:
                    merged[key] = value
        return replace(
            self.config,
            template=self.template,
            added=tuple(n for n in desired if n not in template),
            removed=tuple(n for n in template if n not in desired),
            sections={n: v for n, v in sections.items() if v},
        )
