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
TRACKING_INPUTS = ("text_notes", "message_timing", "device_activity")


@dataclass(frozen=True)
class Family:
    name: str
    timezone: str
    takeout_budget_cents: int
    staples: tuple[str, ...]
    created_at: datetime
    task_owners: dict[str, int] = field(default_factory=dict, hash=False)  # kind -> member id
    handover_cost: float = 10.0


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
