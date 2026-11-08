"""Typed records for the family, its members and what they've linked."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
from typing import Literal

Direction = Literal["in", "out"]


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


# Inputs the energy engine may watch about a person. Each can be switched off.
TRACKING_INPUTS = ("text_notes", "message_timing", "device_activity", "calendar", "reactions")


@dataclass(frozen=True)
class Workspace:
    """CR9: what a Themi serves: a family, a person's work, a tutoring family. Its template
    says which modules, roles and persona it has."""

    name: str
    timezone: str
    created_at: datetime
    task_owners: dict[str, int] = field(default_factory=dict, hash=False)  # kind -> member id
    handover_cost: float = 10.0
    template: str = "family"


Family = Workspace  # CR9: the name every caller used; a family is a workspace


DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class BusyTime:
    """A weekly window when Themi holds its own messages, like quiet hours (e.g. work)."""

    days: tuple[int, ...]  # 0 is Monday
    start: time
    end: time  # same day, after start; nights are what quiet hours are for

    def covers(self, local: datetime) -> bool:
        return local.weekday() in self.days and self.start <= local.time() < self.end

    def label(self) -> str:
        days = sorted(self.days)
        if len(days) > 2 and days == list(range(days[0], days[-1] + 1)):
            named = f"{DAY_NAMES[days[0]]}-{DAY_NAMES[days[-1]]}"
        else:
            named = ", ".join(DAY_NAMES[d] for d in days)
        return f"{named} {self.start:%H:%M}-{self.end:%H:%M}"


@dataclass(frozen=True)
class Member:
    id: int
    name: str
    role: Role
    telegram_user_id: int | None
    quiet_start: time
    quiet_end: time
    daily_limit: int
    pda_enabled: bool
    pda_strength: int
    recovery_hours: float
    tracking: dict[str, bool] = field(hash=False)
    created_at: datetime
    kind_costs: dict[str, float] = field(default_factory=dict, hash=False)
    email: str | None = None  # Google sign-in address for the website
    busy_times: tuple[BusyTime, ...] = ()
    phrasing: str = "plain"  # plain (say it straight) or gentle (indirect, low-key), idea #12
    phrasing_notes: str = ""  # their own words on how they like things said
    listen_first: bool = True  # feelings get listening; ask before problem-solving (F22e)
    day_ends: int = 0  # F34j: their day rolls over at this hour after midnight (0 to 4)
    # The website's menu bar, in order (F28c): paths, at most MENU_BAR_MAX; None: the usual.
    menu_bar: tuple[str, ...] | None = None
    # CM1a: talk with a plain chat model; a background pass picks out tasks (CM1b).
    # CR20b: the channels they're on ("telegram", "web_chat"), from member_identities.
    channels: tuple[str, ...] = ()

    @property
    def reachable(self) -> bool:
        """Themi can write to them on some channel (CR20b; Telegram only, before)."""
        return bool(self.channels)

    def kind_cost(self, kind: str) -> float:
        return self.kind_costs.get(kind, 1.0)

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    def tracks(self, input_name: str) -> bool:
        return self.tracking.get(input_name, True)


@dataclass(frozen=True)
class LinkedAccount:
    id: int
    member_id: int
    provider: str
    address: str
    watched: bool
    labels: tuple[str, ...]
    enabled: bool
    created_at: datetime
    urgent_senders: tuple[str, ...] = ()  # addresses or @domains that always count as urgent
    scopes: tuple[str, ...] = ()  # what Google granted at the latest link

    def allows(self, *scopes: str) -> bool:
        return all(scope in self.scopes for scope in scopes)

    def is_urgent_sender(self, address: str) -> bool:
        return any(sender_matches(pattern, address) for pattern in self.urgent_senders)


def sender_matches(pattern: str, address: str) -> bool:
    """An exact address, or `@domain`, which covers its subdomains too."""
    address = address.strip().lower()
    if pattern.startswith("@"):
        return address.endswith(pattern) or address.endswith(f".{pattern[1:]}")
    return address == pattern


@dataclass(frozen=True)
class Device:
    id: int
    provider: str
    external_id: str
    name: str
    appliance: str | None
    created_at: datetime


@dataclass(frozen=True)
class LoggedMessage:
    id: int
    member_id: int
    direction: Direction
    text: str
    kind: str
    telegram_message_id: int | None
    created_at: datetime
