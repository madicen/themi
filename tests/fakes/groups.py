"""CR8b: the tool groups as the tables they were before modules registered them, built from
every known group (the installed modules', CR10b1), for tests and evals that read them so."""

from __future__ import annotations

from collections.abc import Sequence

from themi.config import all_groups
from themi.core.tools import ToolRegistry

CATALOG = all_groups()

GROUPS: dict[str, tuple[str, str]] = {g.name: (g.description, g.words) for g in CATALOG}
TOOL_GROUPS: dict[str, str] = {tool: g.name for g in CATALOG for tool in g.tools}
GROUP_EXAMPLES: dict[str, tuple[str, ...]] = {g.name: g.examples for g in CATALOG}

_EVERY = ToolRegistry()
for _group in CATALOG:
    _EVERY.add_group(_group)


def choose_groups(texts: Sequence[str]) -> set[str]:
    """The groups these messages call for, among every known group."""
    return _EVERY.choose_groups(texts)


def with_every_group(registry: ToolRegistry) -> ToolRegistry:
    """A registry as the full family app has it: every known group added (CR8b)."""
    for group in CATALOG:
        registry.add_group(group)
    return registry
