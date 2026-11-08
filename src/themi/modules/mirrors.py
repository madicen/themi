"""CR21b: displays and apps that keep Themi's lists, tasks or routines in step (a mirror):
the Cozyla wall today. The standard modules know them only through this seam, never by name.

A mirror registers itself (`ctx.mirror`) with where people see things ("on the wall", for
"Ticked off on the wall: ...") and the longest list item it takes. It keeps its own tables
(which list it keeps, its copy of each item, what it has seen ticked), and hears of changes:

- `list_keepers`: which mirror keeps a list in step, if any (lists ask, for an item's limit
  and for saying where else a list is);
- `items_leaving` and `lists_leaving`: items and lists about to go, so the mirror can take
  its copies away too;
- `items_reset`: an item that has stopped being one of the mirror's (a section heading now).

Ticks coming back from a mirror go through the modules' own calls (`TaskBoard.complete`
with `ticked_on`, a routine's tick), and its "ticked there" praise is `praise.ticked_there`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field


class MirrorError(Exception):
    """CR21c: a mirror couldn't be reached or refused (its own errors are these), so a
    feature that asks one (the dishwasher, of the wall's routines) can tell it's that."""


@dataclass(frozen=True)
class Mirror:
    name: str  # "cozyla"
    where: str  # "on the wall": where people see what it keeps
    item_limit: int | None = None  # the longest list item it takes


@dataclass
class Mirrors:
    mirrors: dict[str, Mirror] = field(default_factory=dict)
    list_keepers: list[Callable[[int], Mirror | None]] = field(default_factory=list)
    items_leaving: list[Callable[[Sequence[int]], None]] = field(default_factory=list)
    lists_leaving: list[Callable[[int], None]] = field(default_factory=list)
    items_reset: list[Callable[[int], None]] = field(default_factory=list)

    def add(self, mirror: Mirror) -> None:
        self.mirrors[mirror.name] = mirror

    def keeping_list(self, list_id: int) -> Mirror | None:
        """The mirror that keeps this list in step, if any."""
        for keeper in self.list_keepers:
            if (mirror := keeper(list_id)) is not None:
                return mirror
        return None

    def leaving(self, item_ids: Sequence[int]) -> None:
        if item_ids:
            for hear in self.items_leaving:
                hear(item_ids)

    def list_leaving(self, list_id: int) -> None:
        for hear in self.lists_leaving:
            hear(list_id)

    def reset(self, item_id: int) -> None:
        for hear in self.items_reset:
            hear(item_id)
