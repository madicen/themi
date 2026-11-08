"""Modules: how Themi's features plug into its core (the core refactor, CR1).

A module is a class with a unique `name`, the modules it `requires`, the ones it uses when
they're there (`optional`), and an `install(ctx)` that adds its tools, commands, jobs and
the rest through a `ModuleContext`. The loader orders modules so each comes after what it
requires and otherwise keeps the order it was given, which keeps menus and hook lists in
the order people already see.

    class BreaksModule(Module):
        name = "breaks"

        def install(self, ctx: ModuleContext) -> None:
            ctx.provide(Breaks(ctx.services)).install()

Core never imports a module (`tools/check_layers.py`).
"""

from __future__ import annotations

from themi.modules.base import (
    KINDS,
    Module,
    ModuleError,
    ModuleKind,
    ModuleSetup,
    PeriodicTask,
    SetupStep,
    as_job,
)
from themi.modules.context import ModuleContext
from themi.modules.loader import load, order

__all__ = [
    "KINDS",
    "Module",
    "ModuleContext",
    "ModuleError",
    "ModuleKind",
    "ModuleSetup",
    "PeriodicTask",
    "SetupStep",
    "as_job",
    "load",
    "order",
]
