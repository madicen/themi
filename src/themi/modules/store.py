"""SP2: where the Modules page keeps what admins set.

- `ModuleSecrets`: a module's secrets (API keys, passwords, bot tokens), encrypted with the
  secret key, one row per field. A module's settings read the environment first, then
  these, then its themi.toml section, then the default (`themi.modules.settings`).
- `DraftStore`: the one set of changes waiting for a restart (SP6 applies it): the
  template, modules turned on or off, plain settings, and secrets to set or clear, still
  encrypted, with who changed what.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.storage.db import Database
    from themi.storage.secrets import Cipher, Secret


@dataclass(frozen=True)
class SecretInfo:
    module: str
    field: str
    set_by: int | None
    set_at: str
    ending: str  # the value's last four characters, to recognise it by


class ModuleSecrets:
    def __init__(self, db: Database, cipher: Cipher) -> None:
        self._db = db
        self._cipher = cipher

    def set(self, module: str, name: str, value: str | Secret, member_id: int | None) -> None:
        self._db.execute(
            "INSERT INTO module_secrets (module, field, ciphertext, set_by, set_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(module, field) DO UPDATE SET "
            "ciphertext = excluded.ciphertext, set_by = excluded.set_by, set_at = excluded.set_at",
            (module, name, self._cipher.encrypt(value), member_id, to_utc_iso(clock.now())),
        )

    def clear(self, module: str, name: str) -> None:
        self._db.execute(
            "DELETE FROM module_secrets WHERE module = ? AND field = ?", (module, name)
        )

    def all(self) -> dict[str, dict[str, Secret]]:
        """Every stored secret, by module and field."""
        out: dict[str, dict[str, Secret]] = {}
        for row in self._db.query("SELECT module, field, ciphertext FROM module_secrets"):
            out.setdefault(row["module"], {})[row["field"]] = self._cipher.decrypt(
                row["ciphertext"]
            )
        return out

    def info(self, module: str) -> dict[str, SecretInfo]:
        """What's stored for a module, without the values: for the page."""
        out = {}
        for row in self._db.query(
            "SELECT field, ciphertext, set_by, set_at FROM module_secrets WHERE module = ?",
            (module,),
        ):
            value = self._cipher.decrypt(row["ciphertext"]).reveal()
            out[row["field"]] = SecretInfo(
                module, row["field"], row["set_by"], row["set_at"], value[-4:]
            )
        return out


@dataclass
class Draft:
    """Changes waiting for a restart. `None` for the template: unchanged."""

    template: str | None = None
    modules: dict[str, bool] = field(default_factory=dict)  # name -> on (True) or off
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)  # plain values
    # name -> field -> the new value, encrypted (a Fernet token as text), or None to clear
    secrets: dict[str, dict[str, str | None]] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)  # who changed what, when

    def count(self) -> int:
        """How many changes wait: the template, each module, each setting."""
        fields = sum(len(v) for v in self.sections.values())
        secrets = sum(len(v) for v in self.secrets.values())
        return (1 if self.template else 0) + len(self.modules) + fields + secrets

    def is_empty(self) -> bool:
        return not (self.template or self.modules or self.sections or self.secrets)

    def put_secret(self, cipher: Cipher, module: str, name: str, value: str | None) -> None:
        """A secret to set (encrypted here, never kept in the clear) or, None, to clear."""
        token = cipher.encrypt(value).decode() if value is not None else None
        self.secrets.setdefault(module, {})[name] = token

    def secret(self, cipher: Cipher, module: str, name: str) -> Secret | None:
        token = self.secrets.get(module, {}).get(name)
        return cipher.decrypt(token.encode()) if token else None

    def note(self, member_id: int | None, what: str) -> None:
        self.log.append({"by": member_id, "what": what, "at": to_utc_iso(clock.now())})


class DraftStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self) -> Draft | None:
        body = self._db.scalar("SELECT body FROM config_drafts WHERE id = 1")
        if body is None:
            return None
        data = json.loads(body)
        return Draft(
            template=data.get("template"),
            modules={str(k): bool(v) for k, v in data.get("modules", {}).items()},
            sections={str(k): dict(v) for k, v in data.get("sections", {}).items()},
            secrets={str(k): dict(v) for k, v in data.get("secrets", {}).items()},
            log=list(data.get("log", [])),
        )

    def save(self, draft: Draft, member_id: int | None) -> None:
        if draft.is_empty():
            self.discard()
            return
        self._db.execute(
            "INSERT INTO config_drafts (id, body, updated_by, updated_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET body = excluded.body, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (json.dumps(asdict(draft)), member_id, to_utc_iso(clock.now())),
        )

    def discard(self) -> None:
        self._db.execute("DELETE FROM config_drafts WHERE id = 1")


class ConfigAudit:
    """SP5: who changed what on the Modules page, tested what, and restarted when."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def note(self, member_id: int | None, what: str) -> None:
        self._db.execute(
            "INSERT INTO config_audit (member_id, what, at) VALUES (?, ?, ?)",
            (member_id, what, to_utc_iso(clock.now())),
        )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT a.what, a.at, m.name FROM config_audit a "
            "LEFT JOIN members m ON m.id = a.member_id ORDER BY a.id DESC LIMIT ?",
            (limit,),
        )
