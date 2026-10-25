"""Server settings, read from the environment (and an optional `.env` file).

Real environment variables win over `.env`. Missing or malformed required
values stop startup with a message that says exactly what to set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from themi.storage.secrets import Cipher, Secret, SecretKeyError

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class SettingsError(Exception):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    db_path: Path
    secret_key: Secret
    public_url: str = ""
    telegram_bot_token: Secret | None = None
    log_level: LogLevel = "INFO"

    def cipher(self) -> Cipher:
        return Cipher(self.secret_key)

    @classmethod
    def load(
        cls, env: Mapping[str, str] | None = None, dotenv: Path | None = Path(".env")
    ) -> Settings:
        values = dict(read_dotenv(dotenv)) if dotenv is not None else {}
        values.update(os.environ if env is None else env)
        return cls.from_mapping(values)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> Settings:
        def get(name: str) -> str:
            return values.get(name, "").strip()

        problems = []
        key = get("THEMI_SECRET_KEY")
        key_file = get("THEMI_SECRET_KEY_FILE")
        if not key and key_file:
            try:
                key = Path(key_file).read_text().strip()
            except OSError as exc:
                problems.append(f"THEMI_SECRET_KEY_FILE ({key_file}) can't be read: {exc}")
        if not key and not problems:
            problems.append(
                "THEMI_SECRET_KEY (or THEMI_SECRET_KEY_FILE) is required; "
                "generate a key with `themi keygen`"
            )
        if key:
            try:
                Cipher(key)
            except SecretKeyError as exc:
                problems.append(str(exc))

        level = (get("THEMI_LOG_LEVEL") or "INFO").upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            problems.append(f"THEMI_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR, not {level}")

        if problems:
            raise SettingsError("Themi can't start:\n  - " + "\n  - ".join(problems))

        token = get("TELEGRAM_BOT_TOKEN")
        return cls(
            db_path=Path(get("THEMI_DB_PATH") or "data/themi.db"),
            secret_key=Secret(key),
            public_url=get("THEMI_PUBLIC_URL").rstrip("/"),
            telegram_bot_token=Secret(token) if token else None,
            log_level=level,  # type: ignore[arg-type]  # validated above
        )


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines; ignores blanks, comments and surrounding quotes."""
    if not path.exists():
        return {}
    values = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values
