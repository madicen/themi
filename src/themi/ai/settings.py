"""Each member's AI backends and which ones handle each task.

A backend is a provider a member has set up once: its kind, default model,
address and (encrypted) key. A route lists, per task, the backends to try in
order, optionally overriding the model. Keys are write-only from the
outside: listings say whether a key is set, and only the router ever
decrypts one, and only for that member's own requests.

New members start on Gemini's free tier. The default backend has no key
until the member adds one on the website.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, get_args

from themi import clock
from themi.accounts.store import (
    SYSTEM,
    Actor,
    InvalidValue,
    NotFound,
    PermissionDenied,
    SystemActor,
)
from themi.ai.adapters import AdapterConfig, AdapterKind
from themi.ai.adapters.gemini import DEFAULT_MODEL as GEMINI_CHAT_MODEL
from themi.ai.adapters.gemini import DEFAULT_TRANSCRIPTION_MODEL as GEMINI_AUDIO_MODEL
from themi.storage.db import Database
from themi.storage.secrets import Cipher, Secret


class AITask(StrEnum):
    CONVERSATION = "conversation"
    PDA_REWRITE = "pda_rewrite"
    EMAIL_TRIAGE = "email_triage"
    STRUCTURED_MISC = "structured_misc"
    TRANSCRIPTION = "transcription"


ADAPTER_KINDS: tuple[str, ...] = get_args(AdapterKind)
DEFAULT_BACKEND_LABEL = "Gemini (free tier)"
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Backend:
    """A backend as anyone outside the router sees it: no key, just whether one is set."""

    id: int
    member_id: int
    label: str
    kind: str
    model: str
    base_url: str | None
    has_key: bool
    timeout: float
    supports_tools: bool
    supports_structured: bool
    supports_audio: bool
    effort: str | None


@dataclass(frozen=True)
class RouteEntry:
    backend_id: int
    model: str | None = None


@dataclass(frozen=True)
class ResolvedEntry:
    """One step of a member's chain for a task, ready to build a provider from."""

    backend_id: int
    label: str
    config: AdapterConfig


def _backend_from_row(row: dict[str, Any]) -> Backend:
    return Backend(
        id=row["id"],
        member_id=row["member_id"],
        label=row["label"],
        kind=row["kind"],
        model=row["model"],
        base_url=row["base_url"],
        has_key=row["api_key"] is not None,
        timeout=row["timeout"],
        supports_tools=bool(row["supports_tools"]),
        supports_structured=bool(row["supports_structured"]),
        supports_audio=bool(row["supports_audio"]),
        effort=row["effort"],
    )


class AISettingsStore:
    def __init__(self, db: Database, cipher: Cipher) -> None:
        self.db = db
        self._cipher = cipher

    @staticmethod
    def _require_self(actor: Actor, member_id: int) -> None:
        """AI settings are self-service: not even an admin edits someone else's."""
        if isinstance(actor, SystemActor):
            return
        if actor.id != member_id:
            raise PermissionDenied("members manage only their own AI settings")

    # ----- backends -----------------------------------------------------------

    def add_backend(
        self,
        actor: Actor,
        member_id: int,
        label: str,
        kind: str,
        *,
        model: str = "",
        base_url: str | None = None,
        api_key: Secret | None = None,
        timeout: float = 60.0,
        supports_tools: bool = True,
        supports_structured: bool = True,
        supports_audio: bool = False,
        effort: str | None = None,
    ) -> Backend:
        self._require_self(actor, member_id)
        label = label.strip()
        if not label:
            raise InvalidValue("a backend needs a label")
        _validate(kind, timeout, effort)
        if self.db.one(
            "SELECT 1 FROM ai_backends WHERE member_id = ? AND label = ?", (member_id, label)
        ):
            raise InvalidValue(f"you already have a backend called {label}")
        now = clock.now().isoformat()
        backend_id = self.db.execute(
            "INSERT INTO ai_backends (member_id, label, kind, model, base_url, api_key, timeout, "
            "supports_tools, supports_structured, supports_audio, effort, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                member_id,
                label,
                kind,
                model.strip(),
                (base_url or "").strip().rstrip("/") or None,
                self._cipher.encrypt(api_key) if api_key else None,
                timeout,
                int(supports_tools),
                int(supports_structured),
                int(supports_audio),
                effort,
                now,
                now,
            ),
        )
        return self.get_backend(backend_id)

    def get_backend(self, backend_id: int) -> Backend:
        row = self.db.one("SELECT * FROM ai_backends WHERE id = ?", (backend_id,))
        if row is None:
            raise NotFound(f"no AI backend with id {backend_id}")
        return _backend_from_row(row)

    def backends(self, member_id: int) -> list[Backend]:
        rows = self.db.query(
            "SELECT * FROM ai_backends WHERE member_id = ? ORDER BY id", (member_id,)
        )
        return [_backend_from_row(r) for r in rows]

    def update_backend(self, actor: Actor, backend_id: int, **changes: Any) -> Backend:
        """Change any add_backend field. `api_key=None` leaves the key; use `clear_key`."""
        backend = self.get_backend(backend_id)
        self._require_self(actor, backend.member_id)
        allowed = {
            "label",
            "model",
            "base_url",
            "api_key",
            "timeout",
            "supports_tools",
            "supports_structured",
            "supports_audio",
            "effort",
            "kind",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise InvalidValue(f"unknown backend fields: {', '.join(sorted(unknown))}")
        _validate(
            changes.get("kind", backend.kind),
            changes.get("timeout", backend.timeout),
            changes.get("effort", backend.effort),
        )
        columns: dict[str, Any] = {}
        for name, value in changes.items():
            if name == "api_key":
                if value is not None:
                    columns["api_key"] = self._cipher.encrypt(value)
            elif name in ("supports_tools", "supports_structured", "supports_audio"):
                columns[name] = int(bool(value))
            elif name == "base_url":
                columns[name] = (value or "").strip().rstrip("/") or None
            elif isinstance(value, str):
                columns[name] = value.strip()
            else:
                columns[name] = value
        if columns:
            columns["updated_at"] = clock.now().isoformat()
            assignments = ", ".join(f"{c} = :{c}" for c in columns)
            self.db.execute(
                f"UPDATE ai_backends SET {assignments} WHERE id = :id",
                {**columns, "id": backend_id},
            )
        return self.get_backend(backend_id)

    def clear_key(self, actor: Actor, backend_id: int) -> Backend:
        backend = self.get_backend(backend_id)
        self._require_self(actor, backend.member_id)
        self.db.execute("UPDATE ai_backends SET api_key = NULL WHERE id = ?", (backend_id,))
        return self.get_backend(backend_id)

    def remove_backend(self, actor: Actor, backend_id: int) -> None:
        """Also removes it from every route (the database cascades)."""
        backend = self.get_backend(backend_id)
        self._require_self(actor, backend.member_id)
        with self.db.transaction():
            self.db.execute("DELETE FROM ai_backends WHERE id = ?", (backend_id,))
            self._compact_positions(backend.member_id)

    # ----- routes -------------------------------------------------------------

    def set_chain(
        self, actor: Actor, member_id: int, task: AITask, entries: Sequence[RouteEntry]
    ) -> None:
        """Replace the ordered list of backends for `task` (first = primary)."""
        self._require_self(actor, member_id)
        task = AITask(task)
        if not entries:
            raise InvalidValue("a task needs at least one backend")
        ids = [e.backend_id for e in entries]
        if len(set(ids)) != len(ids):
            raise InvalidValue("a backend can appear only once in a chain")
        owned = {b.id for b in self.backends(member_id)}
        if not set(ids) <= owned:
            raise PermissionDenied("a chain can only use your own backends")
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM ai_routes WHERE member_id = ? AND task = ?", (member_id, task.value)
            )
            self.db.executemany(
                "INSERT INTO ai_routes (member_id, task, position, backend_id, model) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (member_id, task.value, i, e.backend_id, (e.model or "").strip() or None)
                    for i, e in enumerate(entries)
                ],
            )

    def chain(self, member_id: int, task: AITask) -> list[RouteEntry]:
        rows = self.db.query(
            "SELECT backend_id, model FROM ai_routes WHERE member_id = ? AND task = ? "
            "ORDER BY position",
            (member_id, AITask(task).value),
        )
        return [RouteEntry(r["backend_id"], r["model"]) for r in rows]

    def ensure_defaults(self, member_id: int) -> None:
        """Give a member with no AI settings the Gemini free-tier defaults."""
        with self.db.transaction():
            if self.db.scalar("SELECT COUNT(*) FROM ai_routes WHERE member_id = ?", (member_id,)):
                return
            existing = self.db.one(
                "SELECT id FROM ai_backends WHERE member_id = ? AND label = ?",
                (member_id, DEFAULT_BACKEND_LABEL),
            )
            backend_id = (
                existing["id"]
                if existing
                else self.add_backend(
                    SYSTEM,
                    member_id,
                    DEFAULT_BACKEND_LABEL,
                    "gemini",
                    model=GEMINI_CHAT_MODEL,
                    supports_audio=True,
                ).id
            )
            for task in AITask:
                model = GEMINI_AUDIO_MODEL if task is AITask.TRANSCRIPTION else None
                self.set_chain(SYSTEM, member_id, task, [RouteEntry(backend_id, model)])

    def resolve(self, member_id: int, task: AITask) -> list[ResolvedEntry]:
        """The member's chain for `task` with keys decrypted. For the router only."""
        rows = self.db.query(
            "SELECT b.*, r.model AS route_model FROM ai_routes r "
            "JOIN ai_backends b ON b.id = r.backend_id "
            "WHERE r.member_id = ? AND r.task = ? AND b.member_id = r.member_id "
            "ORDER BY r.position",
            (member_id, AITask(task).value),
        )
        resolved = []
        for row in rows:
            config = AdapterConfig(
                kind=row["kind"],
                model=row["route_model"] or row["model"],
                api_key=self._cipher.decrypt(row["api_key"]) if row["api_key"] else None,
                base_url=row["base_url"],
                timeout=row["timeout"],
                supports_tools=bool(row["supports_tools"]),
                supports_structured=bool(row["supports_structured"]),
                supports_audio=bool(row["supports_audio"]),
                effort=row["effort"],
            )
            resolved.append(ResolvedEntry(row["id"], row["label"], config))
        return resolved

    def _compact_positions(self, member_id: int) -> None:
        for task in AITask:
            entries = self.chain(member_id, task)
            self.db.execute(
                "DELETE FROM ai_routes WHERE member_id = ? AND task = ?", (member_id, task.value)
            )
            self.db.executemany(
                "INSERT INTO ai_routes (member_id, task, position, backend_id, model) "
                "VALUES (?, ?, ?, ?, ?)",
                [(member_id, task.value, i, e.backend_id, e.model) for i, e in enumerate(entries)],
            )


def _validate(kind: str, timeout: float, effort: str | None) -> None:
    if kind not in ADAPTER_KINDS:
        raise InvalidValue(f"unknown AI provider {kind!r}; expected one of {ADAPTER_KINDS}")
    if not 1 <= timeout <= 600:
        raise InvalidValue("timeout must be between 1 and 600 seconds")
    if effort is not None and effort not in EFFORTS:
        raise InvalidValue(f"effort must be one of {EFFORTS}")
