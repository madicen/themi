"""MP1: the groups the Modules page lists modules in.

A module's `kind` says how it plugs in (a channel, a connector); its `group` says what it's
for (Cooking, Email), and is where the Modules page lists it. The core declares the groups
its own modules are in, here; a pack declares its own groups beside its modules, and core
never names them. The page finds the groups through the modules that point at them.

Inside a group, a module that requires another module of the same group is shown as its
add-on, indented beneath it. A module can also be listed as a guest in other groups
(`also_in`): the Oven is in Home and devices, and shown under Cooking too.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from themi.modules.base import ModuleError

if TYPE_CHECKING:
    from themi.modules.base import Module


@dataclass(frozen=True)
class ModuleGroup:
    id: str
    title: str
    summary: str
    order: int  # place on the page, smallest first
    # MP2: what "Turn on the group" ticks. None: every module in it that needs no account.
    starter: tuple[str, ...] | None = None
    folded: bool = False  # starts closed on the page


TALKING = ModuleGroup(
    "talking",
    "Talking to Themi",
    "Where the family writes to Themi and gets its answers.",
    10,
    starter=("telegram", "web_chat"),
)
AI = ModuleGroup(
    "ai",
    "AI",
    "The AI services that answer. Themi needs at least one.",
    20,
    starter=("gemini",),
)
VOICE_AND_PICTURES = ModuleGroup(
    "voice_and_pictures",
    "Voice and pictures",
    "Voice notes and pictures sent to Themi, and pictures it draws.",
    30,
)
TASKS = ModuleGroup(
    "tasks",
    "Tasks",
    "Tasks, chores, lists and reminders, and who's doing what.",
    40,
)
YOUR_DAY = ModuleGroup(
    "your_day",
    "Your day",
    "The shape of the day: summaries, focus, breaks and check-ins.",
    50,
)
SERVICES = ModuleGroup(
    "services",
    "Services",
    "Outside services other modules build on.",
    130,
    starter=("google", "weather", "web_search"),
)
BEHIND_THE_SCENES = ModuleGroup(
    "behind_the_scenes",
    "Behind the scenes",
    "How Themi remembers, takes commands and learns from its mistakes. Rarely changed.",
    140,
    folded=True,
)
OTHER = ModuleGroup("other", "Other", "Modules that don't say where they belong.", 999)


def group_of(cls: type[Module]) -> ModuleGroup:
    return cls.group or OTHER


def known_groups(classes: Iterable[type[Module]]) -> list[ModuleGroup]:
    """Every group the modules point at, in page order. Two different groups with one id
    are a mistake in a pack."""
    found: dict[str, ModuleGroup] = {}
    for cls in classes:
        for group in (group_of(cls), *cls.also_in):
            seen = found.setdefault(group.id, group)
            if seen != group:
                raise ModuleError(f"two different module groups are called {group.id}")
    return sorted(found.values(), key=lambda g: (g.order, g.title))


def members(group: ModuleGroup, known: Mapping[str, type[Module]]) -> list[str]:
    return sorted(n for n, c in known.items() if group_of(c).id == group.id)


def guests(group: ModuleGroup, known: Mapping[str, type[Module]]) -> list[str]:
    return sorted(n for n, c in known.items() if any(g.id == group.id for g in c.also_in))


def starter(group: ModuleGroup, known: Mapping[str, type[Module]]) -> list[str]:
    """The modules "Turn on the group" ticks (MP2)."""
    names = members(group, known)
    if group.starter is not None:
        return [n for n in names if n in group.starter]
    return [n for n in names if known[n].needs_accounts is None]


def parent_in_group(name: str, names: Iterable[str], known: Mapping[str, type[Module]]) -> str:
    """The module in `names` that `name` is shown under: of what it requires there, the
    one furthest down (Cooking along needs the cookbook and Recipe groceries, which needs
    the cookbook: it goes under Recipe groceries). "" for a lead."""
    inside = set(names)
    depth: dict[str, int] = {}

    def depth_of(n: str) -> int:
        if n not in depth:
            depth[n] = 0  # a loop can't recurse forever (the loader refuses loops anyway)
            reqs = [r for r in known[n].requires if r in inside]
            depth[n] = 1 + max((depth_of(r) for r in reqs), default=-1)
        return depth[n]

    reqs = [r for r in known[name].requires if r in inside]
    if not reqs:
        return ""
    return max(reqs, key=lambda r: (depth_of(r), r))


def tree(
    names: Iterable[str], known: Mapping[str, type[Module]], title: Mapping[str, str]
) -> list[tuple[str, int]]:
    """`names` in page order with each one's indent, add-ons under what they build on. At
    each level, the ones with add-ons of their own come first, then the rest, by title."""
    names = list(names)
    children: dict[str, list[str]] = {n: [] for n in names}
    leads = []
    for n in names:
        parent = parent_in_group(n, names, known)
        (children[parent] if parent else leads).append(n)

    def key(n: str) -> tuple[bool, str]:
        return (not children[n], title[n].lower())

    out: list[tuple[str, int]] = []

    def visit(n: str, level: int) -> None:
        out.append((n, level))
        for child in sorted(children[n], key=key):
            visit(child, level + 1)

    for lead in sorted(leads, key=key):
        visit(lead, 0)
    return out
