"""Reading and changing the family, members, invites and linked accounts.

Every change takes an `actor`: the member making it, or `SYSTEM` for the
server operator at the command line. Permission rules live here so the bot,
website and CLI all enforce the same ones:

- Only admins (or SYSTEM) manage members, roles, devices and family settings.
- Members change their own personal settings and linked accounts.
- The family always keeps at least one admin.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from themi import clock
from themi.accounts.models import (
    TRACKING_INPUTS,
    BusyTime,
    Device,
    Direction,
    Family,
    LinkedAccount,
    LoggedMessage,
    Member,
    Role,
)
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret


class SystemActor:
    """The server operator, acting through the CLI on the machine itself."""

    def __repr__(self) -> str:
        return "SYSTEM"


SYSTEM = SystemActor()
Actor = Member | SystemActor

INVITE_TTL = timedelta(hours=24)
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
PROVIDERS = ("gmail",)
DEVICE_PROVIDERS = ("lg_thinq", "tuya", "catgenie")
APPLIANCES = ("washer", "dryer", "dishwasher", "feeder", "litter_box")
TASK_KINDS = ("text", "call", "physical", "errand")
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class AccountsError(Exception):
    pass


class PermissionDenied(AccountsError):
    pass


class NotFound(AccountsError):
    pass


class InviteError(AccountsError):
    """Deliberately vague: an unknown, used and expired code all look the same."""


class InvalidValue(AccountsError, ValueError):
    pass


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _parse_hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError) as exc:
        raise InvalidValue(f"expected a time like 21:30, got {value!r}") from exc


MAX_BUSY_TIMES = 10
PHRASING_STYLES = ("plain", "gentle")
MAX_PHRASING_NOTES = 500


def _busy_json(busy: BusyTime) -> dict[str, Any]:
    if not busy.days:
        raise InvalidValue("a busy time needs at least one day")
    if any(day not in range(7) for day in busy.days):
        raise InvalidValue("busy days must be days of the week (0 is Monday)")
    if busy.end <= busy.start:
        raise InvalidValue("a busy time has to end after it starts, on the same day")
    return {
        "days": sorted(set(busy.days)),
        "start": busy.start.strftime("%H:%M"),
        "end": busy.end.strftime("%H:%M"),
    }


def _hash_code(code: str) -> str:
    normalised = "".join(ch for ch in code.upper() if ch.isalnum())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _member_from_row(row: dict[str, Any]) -> Member:
    return Member(
        id=row["id"],
        name=row["name"],
        role=Role(row["role"]),
        telegram_user_id=row["telegram_user_id"],
        quiet_start=_parse_hhmm(row["quiet_start"]),
        quiet_end=_parse_hhmm(row["quiet_end"]),
        daily_limit=row["daily_limit"],
        pda_enabled=bool(row["pda_enabled"]),
        pda_strength=row["pda_strength"],
        recovery_hours=row["recovery_hours"],
        tracking={name: json.loads(row["tracking"]).get(name, True) for name in TRACKING_INPUTS},
        created_at=_parse_dt(row["created_at"]),
        kind_costs={k: float(v) for k, v in json.loads(row["kind_costs"]).items()},
        email=row["email"],
        busy_times=tuple(
            BusyTime(tuple(b["days"]), _parse_hhmm(b["start"]), _parse_hhmm(b["end"]))
            for b in json.loads(row["busy_times"])
        ),
        phrasing=row["phrasing"],
        phrasing_notes=row["phrasing_notes"],
    )


def _account_from_row(row: dict[str, Any]) -> LinkedAccount:
    return LinkedAccount(
        id=row["id"],
        member_id=row["member_id"],
        provider=row["provider"],
        address=row["address"],
        watched=bool(row["watched"]),
        labels=tuple(json.loads(row["labels"])),
        enabled=bool(row["enabled"]),
        created_at=_parse_dt(row["created_at"]),
        urgent_senders=tuple(json.loads(row["urgent_senders"])),
        scopes=tuple(json.loads(row["scopes"])),
    )


def _device_from_row(row: dict[str, Any]) -> Device:
    return Device(
        id=row["id"],
        provider=row["provider"],
        external_id=row["external_id"],
        name=row["name"],
        appliance=row["appliance"],
        created_at=_parse_dt(row["created_at"]),
    )


class AccountStore:
    def __init__(self, db: Database, cipher: Cipher) -> None:
        self.db = db
        self._cipher = cipher

    @property
    def cipher(self) -> Cipher:
        return self._cipher

    # ----- permission helpers -------------------------------------------------

    def _require_admin(self, actor: Actor) -> None:
        if isinstance(actor, SystemActor):
            return
        # Re-read the role: a Member object held elsewhere may predate a demotion.
        row = self.db.one("SELECT role FROM members WHERE id = ?", (actor.id,))
        if row is None or row["role"] != Role.ADMIN.value:
            raise PermissionDenied("only an admin can do that")

    @staticmethod
    def _require_self(actor: Actor, member_id: int) -> None:
        if isinstance(actor, SystemActor):
            return
        if actor.id != member_id:
            raise PermissionDenied("members can only change their own settings")

    # ----- family -------------------------------------------------------------

    def get_family(self) -> Family | None:
        row = self.db.one("SELECT * FROM family WHERE id = 1")
        if row is None:
            return None
        return Family(
            name=row["name"],
            timezone=row["timezone"],
            takeout_budget_cents=row["takeout_budget_cents"],
            staples=tuple(json.loads(row["staples"])),
            created_at=_parse_dt(row["created_at"]),
            task_owners={k: int(v) for k, v in json.loads(row["task_owners"]).items()},
            handover_cost=float(row["handover_cost"]),
        )

    def create_family(
        self,
        name: str,
        timezone: str,
        takeout_budget_cents: int = 0,
        staples: tuple[str, ...] = (),
    ) -> Family:
        if self.get_family() is not None:
            raise AccountsError("this server already has a family")
        name = name.strip()
        if not name:
            raise InvalidValue("the family needs a name")
        _validate_timezone(timezone)
        if takeout_budget_cents < 0:
            raise InvalidValue("the takeout budget can't be negative")
        now = _iso(clock.now())
        self.db.execute(
            "INSERT INTO family (id, name, timezone, takeout_budget_cents, staples, created_at, "
            "updated_at) VALUES (1, ?, ?, ?, ?, ?, ?)",
            (name, timezone, takeout_budget_cents, json.dumps(list(staples)), now, now),
        )
        family = self.get_family()
        assert family is not None
        return family

    def update_family(
        self,
        actor: Actor,
        *,
        name: str | None = None,
        timezone: str | None = None,
        takeout_budget_cents: int | None = None,
        staples: tuple[str, ...] | None = None,
        task_owners: dict[str, int | None] | None = None,
        handover_cost: float | None = None,
    ) -> Family:
        self._require_admin(actor)
        if self.get_family() is None:
            raise NotFound("no family has been set up yet")
        changes: dict[str, Any] = {}
        if name is not None:
            if not name.strip():
                raise InvalidValue("the family needs a name")
            changes["name"] = name.strip()
        if timezone is not None:
            _validate_timezone(timezone)
            changes["timezone"] = timezone
        if takeout_budget_cents is not None:
            if takeout_budget_cents < 0:
                raise InvalidValue("the takeout budget can't be negative")
            changes["takeout_budget_cents"] = takeout_budget_cents
        if staples is not None:
            changes["staples"] = json.dumps([s.strip() for s in staples if s.strip()])
        if task_owners is not None:
            owners = {}
            for kind, member_id in task_owners.items():
                if kind not in TASK_KINDS:
                    raise InvalidValue(f"unknown task kind {kind!r}")
                if member_id is not None:
                    self.get_member(member_id)
                    owners[kind] = member_id
            changes["task_owners"] = json.dumps(owners)
        if handover_cost is not None:
            if not 0 <= handover_cost <= 50:
                raise InvalidValue("the hand-over cost must be between 0 and 50")
            changes["handover_cost"] = float(handover_cost)
        if changes:
            changes["updated_at"] = _iso(clock.now())
            assignments = ", ".join(f"{column} = :{column}" for column in changes)
            self.db.execute(f"UPDATE family SET {assignments} WHERE id = 1", changes)
        family = self.get_family()
        assert family is not None
        return family

    # ----- members ------------------------------------------------------------

    def list_members(self) -> list[Member]:
        return [_member_from_row(r) for r in self.db.query("SELECT * FROM members ORDER BY id")]

    def get_member(self, member_id: int) -> Member:
        row = self.db.one("SELECT * FROM members WHERE id = ?", (member_id,))
        if row is None:
            raise NotFound(f"no member with id {member_id}")
        return _member_from_row(row)

    def member_by_name(self, name: str) -> Member | None:
        row = self.db.one("SELECT * FROM members WHERE name = ?", (name.strip(),))
        return _member_from_row(row) if row else None

    def member_by_telegram(self, telegram_user_id: int) -> Member | None:
        row = self.db.one("SELECT * FROM members WHERE telegram_user_id = ?", (telegram_user_id,))
        return _member_from_row(row) if row else None

    def member_by_email(self, email: str) -> Member | None:
        row = self.db.one("SELECT * FROM members WHERE lower(email) = ?", (email.strip().lower(),))
        return _member_from_row(row) if row else None

    def set_email(self, actor: Actor, member_id: int, email: str | None) -> Member:
        """The Google address a member signs in with. Admins set it (and SYSTEM, at setup)."""
        self._require_admin(actor)
        self.get_member(member_id)
        address = (email or "").strip().lower() or None
        if address is not None:
            if not EMAIL_PATTERN.fullmatch(address):
                raise InvalidValue(f"{address!r} doesn't look like an email address")
            other = self.member_by_email(address)
            if other is not None and other.id != member_id:
                raise InvalidValue(f"{address} already belongs to {other.name}")
        self.db.execute(
            "UPDATE members SET email = ?, updated_at = ? WHERE id = ?",
            (address, _iso(clock.now()), member_id),
        )
        return self.get_member(member_id)

    def create_member(self, actor: Actor, name: str, role: Role = Role.MEMBER) -> Member:
        if self.get_family() is None:
            raise AccountsError("set up the family before adding members")
        has_members = self.db.scalar("SELECT COUNT(*) FROM members") > 0
        if not has_members and not isinstance(actor, SystemActor):
            raise PermissionDenied("the first member is created from the server")
        if not has_members and role is not Role.ADMIN:
            raise InvalidValue("the first member must be an admin")
        self._require_admin(actor)
        name = name.strip()
        if not name:
            raise InvalidValue("a member needs a name")
        if self.member_by_name(name) is not None:
            raise InvalidValue(f"there's already a member called {name}")
        now = _iso(clock.now())
        member_id = self.db.execute(
            "INSERT INTO members (name, role, tracking, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, role.value, json.dumps(dict.fromkeys(TRACKING_INPUTS, True)), now, now),
        )
        return self.get_member(member_id)

    def update_settings(
        self,
        actor: Actor,
        member_id: int,
        *,
        quiet_start: str | time | None = None,
        quiet_end: str | time | None = None,
        daily_limit: int | None = None,
        pda_enabled: bool | None = None,
        pda_strength: int | None = None,
        recovery_hours: float | None = None,
        tracking: dict[str, bool] | None = None,
        kind_costs: dict[str, float] | None = None,
        busy_times: Sequence[BusyTime] | None = None,
        phrasing: str | None = None,
        phrasing_notes: str | None = None,
    ) -> Member:
        """Personal settings: only the member themselves (or SYSTEM) may change them."""
        self._require_self(actor, member_id)
        member = self.get_member(member_id)
        changes: dict[str, Any] = {}
        if quiet_start is not None:
            changes["quiet_start"] = _parse_hhmm(quiet_start).strftime("%H:%M")
        if quiet_end is not None:
            changes["quiet_end"] = _parse_hhmm(quiet_end).strftime("%H:%M")
        if daily_limit is not None:
            if not 0 <= daily_limit <= 50:
                raise InvalidValue("the daily message limit must be between 0 and 50")
            changes["daily_limit"] = daily_limit
        if pda_enabled is not None:
            changes["pda_enabled"] = int(pda_enabled)
        if pda_strength is not None:
            if not 0 <= pda_strength <= 3:
                raise InvalidValue("PDA shielding strength must be between 0 and 3")
            changes["pda_strength"] = pda_strength
        if recovery_hours is not None:
            if not 0.5 <= recovery_hours <= 72:
                raise InvalidValue("recovery speed must be between 0.5 and 72 hours")
            changes["recovery_hours"] = float(recovery_hours)
        if tracking is not None:
            unknown = set(tracking) - set(TRACKING_INPUTS)
            if unknown:
                raise InvalidValue(f"unknown tracking inputs: {', '.join(sorted(unknown))}")
            changes["tracking"] = json.dumps({**member.tracking, **tracking})
        if kind_costs is not None:
            for kind, multiplier in kind_costs.items():
                if kind not in TASK_KINDS:
                    raise InvalidValue(f"unknown task kind {kind!r}")
                if not 0.25 <= multiplier <= 4:
                    raise InvalidValue("a task-kind cost must be between 0.25 and 4")
            changes["kind_costs"] = json.dumps({**member.kind_costs, **kind_costs})
        if phrasing is not None:
            if phrasing not in PHRASING_STYLES:
                raise InvalidValue("phrasing is plain or gentle")
            changes["phrasing"] = phrasing
        if phrasing_notes is not None:
            if len(phrasing_notes) > MAX_PHRASING_NOTES:
                raise InvalidValue(f"phrasing notes are at most {MAX_PHRASING_NOTES} characters")
            changes["phrasing_notes"] = phrasing_notes.strip()
        if busy_times is not None:
            changes["busy_times"] = json.dumps([_busy_json(b) for b in busy_times])
            if len(busy_times) > MAX_BUSY_TIMES:
                raise InvalidValue(f"at most {MAX_BUSY_TIMES} busy times")
        if changes:
            changes["updated_at"] = _iso(clock.now())
            changes["id"] = member_id
            assignments = ", ".join(f"{c} = :{c}" for c in changes if c != "id")
            self.db.execute(f"UPDATE members SET {assignments} WHERE id = :id", changes)
        return self.get_member(member_id)

    def _admin_count(self) -> int:
        return self.db.scalar("SELECT COUNT(*) FROM members WHERE role = 'admin'")

    def set_role(self, actor: Actor, member_id: int, role: Role) -> Member:
        self._require_admin(actor)
        member = self.get_member(member_id)
        if member.is_admin and role is not Role.ADMIN and self._admin_count() == 1:
            raise InvalidValue("the family needs at least one admin")
        self.db.execute(
            "UPDATE members SET role = ?, updated_at = ? WHERE id = ?",
            (role.value, _iso(clock.now()), member_id),
        )
        return self.get_member(member_id)

    def delete_member(self, actor: Actor, member_id: int) -> None:
        """Removes the member and, by cascade, their linked accounts, messages and invites."""
        self._require_admin(actor)
        member = self.get_member(member_id)
        if member.is_admin and self._admin_count() == 1:
            raise InvalidValue("the family needs at least one admin")
        self.db.execute("DELETE FROM members WHERE id = ?", (member_id,))

    # ----- invites ------------------------------------------------------------

    def create_invite(self, actor: Actor, member_id: int) -> str:
        """Returns a fresh code like `K7QM-3XRP`; any earlier unused code stops working."""
        self._require_admin(actor)
        self.get_member(member_id)
        raw = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(8))
        code = f"{raw[:4]}-{raw[4:]}"
        now = clock.now()
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM invites WHERE member_id = ? AND used_at IS NULL", (member_id,)
            )
            self.db.execute(
                "INSERT INTO invites (code_hash, member_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (_hash_code(code), member_id, _iso(now), _iso(now + INVITE_TTL)),
            )
        return code

    def redeem_invite(self, code: str, telegram_user_id: int) -> Member:
        """Pairs a Telegram account with the invited member. Works once, within 24 hours."""
        now = clock.now()
        with self.db.transaction():
            row = self.db.one(
                "SELECT * FROM invites WHERE code_hash = ? AND used_at IS NULL",
                (_hash_code(code),),
            )
            if row is None or _parse_dt(row["expires_at"]) <= now:
                raise InviteError("that code isn't valid; ask an admin for a new one")
            existing = self.member_by_telegram(telegram_user_id)
            if existing is not None and existing.id != row["member_id"]:
                raise InviteError("this Telegram account is already paired with someone else")
            self.db.execute(
                "UPDATE invites SET used_at = ? WHERE code_hash = ?", (_iso(now), row["code_hash"])
            )
            self.db.execute(
                "UPDATE members SET telegram_user_id = ?, updated_at = ? WHERE id = ?",
                (telegram_user_id, _iso(now), row["member_id"]),
            )
        return self.get_member(row["member_id"])

    # ----- linked accounts ----------------------------------------------------

    def add_linked_account(
        self, actor: Actor, member_id: int, provider: str, address: str, refresh_token: Secret
    ) -> LinkedAccount:
        self._require_self(actor, member_id)
        self.get_member(member_id)
        if provider not in PROVIDERS:
            raise InvalidValue(f"unknown account provider {provider!r}")
        address = address.strip().lower()
        if "@" not in address:
            raise InvalidValue(f"{address!r} doesn't look like an email address")
        if self.db.one(
            "SELECT 1 FROM linked_accounts WHERE provider = ? AND address = ?", (provider, address)
        ):
            raise InvalidValue(f"{address} is already linked")
        account_id = self.db.execute(
            "INSERT INTO linked_accounts (member_id, provider, address, refresh_token, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (member_id, provider, address, self._cipher.encrypt(refresh_token), _iso(clock.now())),
        )
        return self.get_linked_account(account_id)

    def get_linked_account(self, account_id: int) -> LinkedAccount:
        row = self.db.one("SELECT * FROM linked_accounts WHERE id = ?", (account_id,))
        if row is None:
            raise NotFound(f"no linked account with id {account_id}")
        return _account_from_row(row)

    def linked_accounts(self, member_id: int) -> list[LinkedAccount]:
        rows = self.db.query(
            "SELECT * FROM linked_accounts WHERE member_id = ? ORDER BY id", (member_id,)
        )
        return [_account_from_row(r) for r in rows]

    def refresh_token(self, account_id: int) -> Secret:
        row = self.db.one("SELECT refresh_token FROM linked_accounts WHERE id = ?", (account_id,))
        if row is None:
            raise NotFound(f"no linked account with id {account_id}")
        return self._cipher.decrypt(row["refresh_token"])

    def replace_refresh_token(self, account_id: int, refresh_token: Secret) -> None:
        self.get_linked_account(account_id)
        self.db.execute(
            "UPDATE linked_accounts SET refresh_token = ? WHERE id = ?",
            (self._cipher.encrypt(refresh_token), account_id),
        )

    def set_linked_account_scopes(self, account_id: int, scopes: list[str]) -> None:
        """What Google granted at the latest link."""
        self.db.execute(
            "UPDATE linked_accounts SET scopes = ? WHERE id = ?",
            (json.dumps(sorted(set(scopes))), account_id),
        )

    def update_linked_account(
        self,
        actor: Actor,
        account_id: int,
        *,
        watched: bool | None = None,
        urgent_senders: list[str] | None = None,
    ) -> LinkedAccount:
        """A member's own inbox settings: whether it's watched, and its urgent senders."""
        account = self.get_linked_account(account_id)
        self._require_self(actor, account.member_id)
        if watched is not None:
            self.db.execute(
                "UPDATE linked_accounts SET watched = ? WHERE id = ?", (int(watched), account_id)
            )
        if urgent_senders is not None:
            patterns = []
            for raw in urgent_senders:
                if not raw.strip():
                    continue
                pattern = sender_pattern(raw)
                if pattern not in patterns:
                    patterns.append(pattern)
            self.db.execute(
                "UPDATE linked_accounts SET urgent_senders = ? WHERE id = ?",
                (json.dumps(patterns), account_id),
            )
        return self.get_linked_account(account_id)

    def linked_account_by_address(self, provider: str, address: str) -> LinkedAccount | None:
        row = self.db.one(
            "SELECT * FROM linked_accounts WHERE provider = ? AND address = ?",
            (provider, address.strip().lower()),
        )
        return _account_from_row(row) if row else None

    def set_linked_account_enabled(self, account_id: int, enabled: bool) -> None:
        """Off when Google stops accepting the token; on again after a fresh link.

        Turning it back on clears the sync's backoff and its "link again" alert.
        """
        self.get_linked_account(account_id)
        if enabled:
            self.db.execute(
                "UPDATE linked_accounts SET enabled = 1, alerted_at = NULL, poll_after = NULL, "
                "poll_failures = 0 WHERE id = ?",
                (account_id,),
            )
        else:
            self.db.execute("UPDATE linked_accounts SET enabled = 0 WHERE id = ?", (account_id,))

    def remove_linked_account(self, actor: Actor, account_id: int) -> None:
        account = self.get_linked_account(account_id)
        self._require_self(actor, account.member_id)
        self.db.execute("DELETE FROM linked_accounts WHERE id = ?", (account_id,))

    # ----- devices ------------------------------------------------------------

    def add_device(
        self,
        actor: Actor,
        provider: str,
        external_id: str,
        name: str,
        appliance: str | None = None,
        credentials: Secret | None = None,
    ) -> Device:
        self._require_admin(actor)
        if provider not in DEVICE_PROVIDERS:
            raise InvalidValue(f"unknown device provider {provider!r}")
        _validate_appliance(appliance)
        device_id = self.db.execute(
            "INSERT INTO devices (provider, external_id, name, appliance, credentials, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                provider,
                external_id,
                name.strip(),
                appliance,
                self._cipher.encrypt(credentials) if credentials is not None else None,
                _iso(clock.now()),
            ),
        )
        return self.get_device(device_id)

    def get_device(self, device_id: int) -> Device:
        row = self.db.one("SELECT * FROM devices WHERE id = ?", (device_id,))
        if row is None:
            raise NotFound(f"no device with id {device_id}")
        return _device_from_row(row)

    def list_devices(self) -> list[Device]:
        return [_device_from_row(r) for r in self.db.query("SELECT * FROM devices ORDER BY id")]

    def set_device_appliance(self, actor: Actor, device_id: int, appliance: str | None) -> Device:
        self._require_admin(actor)
        _validate_appliance(appliance)
        self.get_device(device_id)
        self.db.execute("UPDATE devices SET appliance = ? WHERE id = ?", (appliance, device_id))
        return self.get_device(device_id)

    def device_credentials(self, device_id: int) -> Secret | None:
        row = self.db.one("SELECT credentials FROM devices WHERE id = ?", (device_id,))
        if row is None:
            raise NotFound(f"no device with id {device_id}")
        return self._cipher.decrypt(row["credentials"]) if row["credentials"] else None

    def remove_device(self, actor: Actor, device_id: int) -> None:
        self._require_admin(actor)
        self.db.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    # ----- message log --------------------------------------------------------

    def log_message(
        self,
        member_id: int,
        direction: Direction,
        text: str,
        kind: str = "chat",
        telegram_message_id: int | None = None,
    ) -> int:
        return self.db.execute(
            "INSERT INTO message_log (member_id, direction, text, kind, telegram_message_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (member_id, direction, text, kind, telegram_message_id, _iso(clock.now())),
        )

    def recent_messages(self, member_id: int, limit: int = 20) -> list[LoggedMessage]:
        """The member's last `limit` messages, oldest first."""
        rows = self.db.query(
            "SELECT * FROM (SELECT * FROM message_log WHERE member_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?) ORDER BY created_at, id",
            (member_id, limit),
        )
        return [
            LoggedMessage(
                id=r["id"],
                member_id=r["member_id"],
                direction=r["direction"],
                text=r["text"],
                kind=r["kind"],
                telegram_message_id=r["telegram_message_id"],
                created_at=_parse_dt(r["created_at"]),
            )
            for r in rows
        ]


def sender_pattern(raw: str) -> str:
    """An address, or `@domain` ("bank.example" means the whole domain)."""
    pattern = raw.strip().lower()
    if not (pattern.startswith("@") or "@" in pattern):
        pattern = f"@{pattern}"
    if pattern.startswith("@"):
        valid = "." in pattern and " " not in pattern and pattern.count("@") == 1
    else:
        valid = bool(EMAIL_PATTERN.fullmatch(pattern))
    if not valid:
        raise InvalidValue(f"{raw.strip()!r} isn't an email address or domain")
    return pattern


def _validate_timezone(name: str) -> None:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidValue(f"{name!r} isn't a timezone name like America/Los_Angeles") from exc


def _validate_appliance(appliance: str | None) -> None:
    if appliance is not None and appliance not in APPLIANCES:
        raise InvalidValue(f"unknown appliance {appliance!r}; expected one of {APPLIANCES}")
