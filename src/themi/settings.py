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

from themi.backup.s3 import S3Config
from themi.backup.snapshots import BackupConfig
from themi.connectors.cozyla.client import CozylaConfig
from themi.connectors.google.oauth import GoogleConfig
from themi.connectors.ourgroceries.client import OurGroceriesConfig
from themi.storage.secrets import Cipher, Secret, SecretKeyError

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
ToolRouting = Literal["groups", "all"]


GOOGLE_ENDPOINT_VARIABLES = {
    "auth_url": "GOOGLE_AUTH_URL",
    "token_url": "GOOGLE_TOKEN_URL",
    "revoke_url": "GOOGLE_REVOKE_URL",
    "userinfo_url": "GOOGLE_USERINFO_URL",
    "gmail_url": "GOOGLE_GMAIL_URL",
    "calendar_url": "GOOGLE_CALENDAR_URL",
}


class SettingsError(Exception):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    db_path: Path
    secret_key: Secret
    public_url: str = ""
    telegram_bot_token: Secret | None = None
    # Another Bot API server, only for the local Telegram simulator (`make dev`).
    telegram_api_url: str = ""
    log_level: LogLevel = "INFO"
    # P5: "groups" sends the core tools and the groups a message calls for (P1); "all"
    # sends every tool, to compare.
    tool_routing: ToolRouting = "groups"
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
    cozyla_email: str = ""
    cozyla_password: Secret | None = None
    cozyla_todo_list: str = ""
    cozyla_device_sn: str = "themi"
    cozyla_chores: bool = False
    # K4: TomTom's routing with live traffic; without it, a free geocoder and an estimate.
    tomtom_api_key: Secret | None = None
    backup: BackupConfig | None = None

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

    def cozyla(self) -> CozylaConfig | None:
        """The Cozyla connection (unofficial API), if a login is set."""
        if not self.cozyla_email or self.cozyla_password is None:
            return None
        return CozylaConfig(
            self.cozyla_email,
            self.cozyla_password,
            self.cozyla_todo_list,
            self.cozyla_device_sn,
            chores=self.cozyla_chores,
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

        routing = (get("THEMI_TOOL_ROUTING") or "groups").lower()
        if routing not in ("groups", "all"):
            problems.append(f"THEMI_TOOL_ROUTING must be groups or all, not {routing}")

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
        if bool(get("COZYLA_EMAIL")) != bool(get("COZYLA_PASSWORD")):
            problems.append("COZYLA_EMAIL and COZYLA_PASSWORD go together; set both or neither")

        backup_names = (
            "THEMI_BACKUP_ENDPOINT",
            "THEMI_BACKUP_BUCKET",
            "THEMI_BACKUP_ACCESS_KEY_ID",
            "THEMI_BACKUP_SECRET_ACCESS_KEY",
        )
        backup_set = [n for n in backup_names if get(n)]
        if backup_set and len(backup_set) != len(backup_names):
            missing = ", ".join(n for n in backup_names if not get(n))
            problems.append(f"backups need all four THEMI_BACKUP_* settings; missing {missing}")
        keep_text = get("THEMI_BACKUP_KEEP_DAYS") or "30"
        if not keep_text.isdigit() or not 1 <= int(keep_text) <= 365:
            problems.append(f"THEMI_BACKUP_KEEP_DAYS must be 1 to 365 days, not {keep_text}")
        telegram_url = get("TELEGRAM_API_URL")
        if telegram_url and not telegram_url.startswith(("http://", "https://")):
            problems.append(f"TELEGRAM_API_URL must be an http(s):// address, not {telegram_url}")

        endpoint = get("THEMI_BACKUP_ENDPOINT")
        local = endpoint.startswith(("http://127.0.0.1", "http://localhost"))  # test fakes
        if endpoint and not (endpoint.startswith("https://") or local):
            problems.append("THEMI_BACKUP_ENDPOINT must be an https:// address")

        if problems:
            raise SettingsError("Themi can't start:\n  - " + "\n  - ".join(problems))

        token = get("TELEGRAM_BOT_TOKEN")
        google_secret = get("GOOGLE_CLIENT_SECRET")
        grocery_password = get("OURGROCERIES_PASSWORD")
        cozyla_password = get("COZYLA_PASSWORD")
        tomtom_key = get("TOMTOM_API_KEY")
        endpoints = {
            field: get(name) for field, name in GOOGLE_ENDPOINT_VARIABLES.items() if get(name)
        }
        return cls(
            db_path=Path(get("THEMI_DB_PATH") or "data/themi.db"),
            secret_key=Secret(key),
            public_url=get("THEMI_PUBLIC_URL").rstrip("/"),
            telegram_bot_token=Secret(token) if token else None,
            telegram_api_url=telegram_url.rstrip("/"),
            log_level=level,  # type: ignore[arg-type]  # validated above
            tool_routing=routing,  # type: ignore[arg-type]  # validated above
            http_host=get("THEMI_HTTP_HOST") or "127.0.0.1",
            http_port=int(port_text),
            telegram_enabled=get("THEMI_DISABLE_TELEGRAM").lower() not in ("1", "true", "yes"),
            google_client_id=get("GOOGLE_CLIENT_ID"),
            google_client_secret=Secret(google_secret) if google_secret else None,
            google_endpoints=endpoints,
            ourgroceries_username=get("OURGROCERIES_USERNAME"),
            ourgroceries_password=Secret(grocery_password) if grocery_password else None,
            ourgroceries_list=get("OURGROCERIES_LIST") or "Groceries",
            cozyla_email=get("COZYLA_EMAIL"),
            cozyla_password=Secret(cozyla_password) if cozyla_password else None,
            cozyla_todo_list=get("COZYLA_TODO_LIST"),
            cozyla_device_sn=get("COZYLA_DEVICE_SN") or "themi",
            cozyla_chores=get("COZYLA_CHORES").lower() in ("1", "true", "yes"),
            tomtom_api_key=Secret(tomtom_key) if tomtom_key else None,
            backup=BackupConfig(
                S3Config(
                    endpoint.rstrip("/"),
                    get("THEMI_BACKUP_BUCKET"),
                    get("THEMI_BACKUP_ACCESS_KEY_ID"),
                    Secret(get("THEMI_BACKUP_SECRET_ACCESS_KEY")),
                    get("THEMI_BACKUP_REGION") or "auto",
                ),
                prefix=(get("THEMI_BACKUP_PREFIX") or "themi/").lstrip("/"),
                keep_days=int(keep_text),
            )
            if backup_set
            else None,
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
