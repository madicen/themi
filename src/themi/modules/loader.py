"""Ordering and installing modules."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from themi.modules.base import Module, ModuleError

if TYPE_CHECKING:
    from themi.modules.context import ModuleContext


def order(modules: Sequence[Module], installed: Sequence[str] = ()) -> list[Module]:
    """Each module after the ones it requires (and the optional ones present), otherwise in
    the given order. `installed`: names already in place, which count as present."""
    by_name: dict[str, Module] = {}
    for module in modules:
        if not module.name:
            raise ModuleError(f"{type(module).__name__} has no name")
        if module.name in by_name or module.name in installed:
            raise ModuleError(f"module {module.name} is listed twice")
        by_name[module.name] = module
    present = set(by_name) | set(installed)
    for module in modules:
        missing = [r for r in module.requires if r not in present]
        if missing:
            raise ModuleError(
                f"module {module.name} requires {', '.join(missing)}, which isn't in the list"
            )

    def before(module: Module) -> list[str]:
        wanted = (*module.requires, *(o for o in module.optional if o in present))
        return [name for name in wanted if name in by_name]

    done: list[Module] = []
    placed: set[str] = set()
    visiting: list[str] = []

    def place(module: Module) -> None:
        if module.name in placed:
            return
        if module.name in visiting:
            loop = [*visiting[visiting.index(module.name) :], module.name]
            raise ModuleError(f"modules require each other in a loop: {' -> '.join(loop)}")
        visiting.append(module.name)
        for name in before(module):
            place(by_name[name])
        visiting.pop()
        placed.add(module.name)
        done.append(module)

    for module in modules:
        place(module)
    return done


def load(modules: Sequence[Module], ctx: ModuleContext) -> list[Module]:
    """Install `modules` into the context, in order. Returns them in the order installed."""
    return ctx.load(*modules)
