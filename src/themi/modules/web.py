"""CR4: what a module adds to the website: its pages, and their places in the menu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from fastapi import APIRouter

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
