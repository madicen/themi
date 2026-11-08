"""CR4: what a module adds to the website: its pages, and their places in the menu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from fastapi import APIRouter

    from themi.accounts import Member
    from themi.web.kit import Kit

# The More page's groups, in the order they're shown. "Main" is the bar's own three.
MenuGroup = Literal["Main", "You", "Accounts", "Household", "Admin"]
GROUP_ORDER: tuple[MenuGroup, ...] = ("You", "Accounts", "Household", "Admin")


@dataclass(frozen=True)
class MenuEntry:
    href: str
    label: str  # on the More page
    hint: str  # the line under it
    group: MenuGroup
    order: int  # place in its group, smallest first
    admin_only: bool = False
    bar_label: str = ""  # a shorter name on the bar; the label when empty
    icon: str = ""  # an inline SVG path for the bar; a plain dot when empty


@dataclass(frozen=True)
class WebPages:
    """A module's routes (built from the site's `Kit`) and its menu entries."""

    routes: Callable[[Kit], APIRouter]
    menu: tuple[MenuEntry, ...] = ()


# ----- CR17a: the dashboard's panels and the Accounts page's sections, from modules -----

Values = Callable[["Member"], "dict[str, object] | None"]


@dataclass(frozen=True)
class Panel:
    """A panel on the dashboard (a template under the site's templates), placed by `order`
    between "Waiting on you" and "Recently". `values` adds what its template shows."""

    order: int
    template: str
    values: Values | None = None


@dataclass(frozen=True)
class AccountsSection:
    """A part of the Accounts page. A member's own (Google accounts, music) come first;
    `household` ones are rows under "Household connections", shown to admins only.
    `values` adds what its template shows; when it gives None, the section isn't shown."""

    order: int
    template: str
    values: Values | None = None
    household: bool = False


@dataclass(frozen=True)
class WaitingLink:
    """A line in "Waiting on you" that stands for some of the member's waiting actions (the
    noise digest's emails), which then don't get a card each."""

    href: str
    text: str
    held: frozenset[int] = frozenset()  # the actions it stands for


Waiting = Callable[["Member"], "WaitingLink | None"]
