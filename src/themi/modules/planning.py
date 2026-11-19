"""SP5: what a change on the Modules page means, before it's made.

The draft says which modules are turned on or off relative to the template (or, when it
switches template, relative to the new one). From it and the current config:

- `desired`: the modules this Themi will have after a restart, in order;
- `turn_on`: a module and what it needs that isn't there yet;
- `turn_off`: a module and everything that needs it;
- `turn_on_many`, `turn_off_many` (MP2): the same for a group, with what was turned on only
  for something going now ("no longer needed") and the last AI provider kept;
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
# MP5: a template's name -> each role's module list ("*", or names; "-name" leaves one out)
TemplateRoles = Callable[[str], dict[str, tuple[str, ...]]]


@dataclass(frozen=True)
class Change:
    """What one switch would do: the modules turned on (the one asked for last) or off (the
    one asked for first)."""

    on: tuple[str, ...] = ()
    off: tuple[str, ...] = ()
    # MP2: why each turned on is on ("asked", or "needed by <name>")
    why: tuple[tuple[str, str], ...] = ()
    # MP2: on only because something going now needed it, and nothing staying does
    spare: tuple[str, ...] = ()
    # MP2: asked to go but staying, with the reason (the last AI provider)
    kept: tuple[tuple[str, str], ...] = ()


ASKED = "asked"
LAST_AI = "Themi needs at least one AI provider to answer, so this one stays on."


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
    # MP2: why each module that's on now came on, kept past restarts (`module_reasons`)
    reasons: dict[str, str] = field(default_factory=dict)
    template_roles: TemplateRoles = field(default=lambda _name: {})

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

    def reason(self, name: str) -> str:
        """Why `name` is on: the draft's word, then the kept one; template modules and
        anything older count as asked."""
        return self.draft.reasons.get(name) or self.reasons.get(name) or ASKED

    def turn_on(self, name: str) -> Change:
        return self.turn_on_many([name])

    def turn_on_many(self, names: Iterable[str]) -> Change:
        """The modules in `names` and what they need that isn't on yet, each after what it
        needs. A requirement is on because of the first module asked that needs it."""
        desired = set(self.desired())
        on: list[str] = []
        why: dict[str, str] = {}
        for name in names:
            for need in self.needs(name):
                if need not in desired and need not in on:
                    on.append(need)
                    why[need] = f"needed by {name}"
            if name not in desired and name not in on:
                on.append(name)
            if name not in desired or self.reason(name) != ASKED:
                why[name] = ASKED  # asked for, even if something else needed it first
        return Change(on=tuple(on), why=tuple(why.items()))

    def turn_off(self, name: str) -> Change:
        return self.turn_off_many([name])

    def turn_off_many(self, names: Iterable[str]) -> Change:
        """The modules in `names` that are on and everything that needs them; what was on
        only for one of those and is needed by nothing staying (`spare`); and the last AI
        provider, kept."""
        desired = self.desired()
        off: list[str] = []
        for name in names:
            if name in desired and name not in off:
                off.append(name)
                off += [n for n in self.needed_by(name, desired) if n not in off]
        kept: list[tuple[str, str]] = []
        staying_ai = [n for n in desired if n not in off and self._is_ai(n)]
        if not staying_ai:
            last = next((n for n in off if self._is_ai(n)), None)
            if last is not None:
                off.remove(last)
                kept.append((last, LAST_AI))
        return Change(off=tuple(off), spare=tuple(self._spare(off, desired)), kept=tuple(kept))

    def _is_ai(self, name: str) -> bool:
        return name in self.known and self.known[name].kind == "ai"

    def _spare(self, off: list[str], desired: list[str]) -> list[str]:
        """Modules on only because something in `off` (or already spare) needed them, that
        nothing staying needs."""
        gone = set(off)
        spare: list[str] = []
        changed = True
        while changed:
            changed = False
            staying = [n for n in desired if n not in gone]
            for n in staying:
                why = self.reason(n)
                if not why.startswith("needed by "):
                    continue
                if why.removeprefix("needed by ") not in gone:
                    continue
                if any(n in self.needs(other) for other in staying if other != n):
                    continue
                gone.add(n)
                spare.append(n)
                changed = True
                break
        return spare

    def apply(self, change: Change) -> None:
        """Put a change in the draft. A switch back to how the base has it is dropped, so
        turning something on and off again leaves no change."""
        base = set(self.base())
        for name in change.on:
            self._set(name, True, base)
        for name in change.off:
            self._set(name, False, base)
            self.draft.reasons.pop(name, None)
        template = set(self.template_modules(self.template))
        for name, why in change.why:
            if name in template and name not in self.reasons:
                self.draft.reasons.pop(name, None)  # a template module is asked for
            else:
                self.draft.reasons[name] = why

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

    # ----- MP5: who can use what ---------------------------------------------------------

    def roles(self) -> dict[str, tuple[str, ...]]:
        """Each role's module list as it will be: the template's, themi.toml's, the draft's."""
        out = dict(self.template_roles(self.template))
        if not self.draft.template:
            out.update(self.config.roles)
        out.update({role: tuple(modules) for role, modules in self.draft.roles.items()})
        return out

    def may_use(self, role: str, name: str) -> bool:
        modules = self.roles().get(role, ("*",))
        if "*" in modules:
            return f"-{name}" not in modules
        return name in modules

    def let_use(self, role: str, name: str, allowed: bool) -> None:
        """Let `role` use `name`, or not, in the draft."""
        if self.may_use(role, name) == allowed:
            return
        modules = [m for m in self.roles().get(role, ("*",)) if m not in (name, f"-{name}")]
        if "*" in modules and not allowed:
            modules.append(f"-{name}")
        elif "*" not in modules and allowed:
            modules.append(name)
        settled = dict(self.template_roles(self.template))
        if not self.draft.template:
            settled.update(self.config.roles)
        if tuple(modules) == settled.get(role, ("*",)):
            self.draft.roles.pop(role, None)
        else:
            self.draft.roles[role] = modules

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
            roles=self._changed_roles(),
        )

    def _changed_roles(self) -> dict[str, tuple[str, ...]]:
        """MP5: the roles whose lists differ from the template's, for themi.toml."""
        template = self.template_roles(self.template)
        return {
            role: modules
            for role, modules in self.roles().items()
            if modules != template.get(role, ("*",))
        }
