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

from themi.connectors.google.oauth import GoogleConfig
from themi.connectors.ourgroceries.client import OurGroceriesConfig
from themi.storage.secrets import Cipher, Secret, SecretKeyError

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


GOOGLE_ENDPOINT_VARIABLES = {
    "auth_url": "GOOGLE_AUTH_URL",
    "token_url": "GOOGLE_TOKEN_URL",
    "revoke_url": "GOOGLE_REVOKE_URL",
    "userinfo_url": "GOOGLE_USERINFO_URL",
    "gmail_url": "GOOGLE_GMAIL_URL",
}


class SettingsError(Exception):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    db_path: Path
    secret_key: Secret
    public_url: str = ""
    telegram_bot_token: Secret | None = None
    log_level: LogLevel = "INFO"
    http_host: str = "127.0.0.1"
    http_port: int = 8080
    # Off only for smoke tests and diagnostics: the process runs without polling Telegram.
    telegram_enabled: bool = True
    google_client_id: str = ""
    google_client_secret: Secret | None = None
    # Endpoint overrides, only for pointing Themi at a local fake Google.
    google_endpoints: dict[str, str] = {}
    ourgroceries_username: str = ""
    ourgroceries_password: Secret | None = None
    ourgroceries_list: str = "Groceries"

    def cipher(self) -> Cipher:
        return Cipher(self.secret_key)

    def google(self) -> GoogleConfig | None:
        """Google sign-in and linking, if a client id and secret are set."""
        if not self.google_client_id or self.google_client_secret is None:
            return None
        return GoogleConfig(
            self.google_client_id, self.google_client_secret, **self.google_endpoints
        )

    def ourgroceries(self) -> OurGroceriesConfig | None:
        """The OurGroceries mirror, if a login is set."""
        if not self.ourgroceries_username or self.ourgroceries_password is None:
            return None
        return OurGroceriesConfig(
            self.ourgroceries_username, self.ourgroceries_password, self.ourgroceries_list
        )

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

        port_text = get("THEMI_HTTP_PORT") or "8080"
        if not port_text.isdigit() or not 0 <= int(port_text) <= 65535:
            problems.append(f"THEMI_HTTP_PORT must be a port number, not {port_text}")

        if bool(get("GOOGLE_CLIENT_ID")) != bool(get("GOOGLE_CLIENT_SECRET")):
            problems.append(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET go together; set both or neither"
            )

        if bool(get("OURGROCERIES_USERNAME")) != bool(get("OURGROCERIES_PASSWORD")):
            problems.append(
                "OURGROCERIES_USERNAME and OURGROCERIES_PASSWORD go together; set both or neither"
            )

        if problems:
            raise SettingsError("Themi can't start:\n  - " + "\n  - ".join(problems))

        token = get("TELEGRAM_BOT_TOKEN")
        google_secret = get("GOOGLE_CLIENT_SECRET")
        grocery_password = get("OURGROCERIES_PASSWORD")
        endpoints = {
            field: get(name) for field, name in GOOGLE_ENDPOINT_VARIABLES.items() if get(name)
        }
        return cls(
            db_path=Path(get("THEMI_DB_PATH") or "data/themi.db"),
            secret_key=Secret(key),
            public_url=get("THEMI_PUBLIC_URL").rstrip("/"),
            telegram_bot_token=Secret(token) if token else None,
            log_level=level,  # type: ignore[arg-type]  # validated above
            http_host=get("THEMI_HTTP_HOST") or "127.0.0.1",
            http_port=int(port_text),
            telegram_enabled=get("THEMI_DISABLE_TELEGRAM").lower() not in ("1", "true", "yes"),
            google_client_id=get("GOOGLE_CLIENT_ID"),
            google_client_secret=Secret(google_secret) if google_secret else None,
            google_endpoints=endpoints,
            ourgroceries_username=get("OURGROCERIES_USERNAME"),
            ourgroceries_password=Secret(grocery_password) if grocery_password else None,
            ourgroceries_list=get("OURGROCERIES_LIST") or "Groceries",
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
