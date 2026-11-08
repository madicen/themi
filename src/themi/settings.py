"""Server settings, read from the environment (and an optional `.env` file).

Real environment variables win over `.env`. Missing or malformed required
values stop startup with a message that says exactly what to set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from themi.backup.s3 import S3Config
from themi.backup.snapshots import BackupConfig
from themi.storage.secrets import Cipher, Secret, SecretKeyError, generate_key

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
ToolRouting = Literal["groups", "all", "embeddings"]
ConversationRollout = Literal["off", "trial", "on"]


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
    # CM1a-c: conversation mode. "trial": /chat turns it on for whoever asks, and the
    # website shows its switch only to them; "on": the switch is on everyone's settings;
    # "off": not offered, and nobody's turns use it.
    conversation_mode: ConversationRollout = "trial"
    http_host: str = "127.0.0.1"
    http_port: int = 8080
    # Off only for smoke tests and diagnostics: the process runs without polling Telegram.
    telegram_enabled: bool = True
    backup: BackupConfig | None = None
    # D3a: the folder shared with the host's runner, for updates asked for on the website.
    control_dir: Path | None = None
    # CR5b: every variable as read (.env, then the environment), for the modules' own
    # settings (themi.modules.settings). Never shown: it holds their secrets.
    environment: dict[str, str] = Field(default_factory=dict, repr=False)

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
        made = key_beside_database(values)
        if not key and not key_file and made.exists():  # SP2: the one Themi made itself
            try:
                key = made.read_text().strip()
            except OSError as exc:
                problems.append(f"{made} can't be read: {exc}")
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
        if routing not in ("groups", "all", "embeddings"):
            problems.append(f"THEMI_TOOL_ROUTING must be groups, all or embeddings, not {routing}")
        rollout = (get("THEMI_CONVERSATION_MODE") or "trial").lower()
        if rollout not in ("off", "trial", "on"):
            problems.append(f"THEMI_CONVERSATION_MODE must be off, trial or on, not {rollout}")

        port_text = get("THEMI_HTTP_PORT") or "8080"
        if not port_text.isdigit() or not 0 <= int(port_text) <= 65535:
            problems.append(f"THEMI_HTTP_PORT must be a port number, not {port_text}")

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
        return cls(
            db_path=Path(get("THEMI_DB_PATH") or "data/themi.db"),
            secret_key=Secret(key),
            public_url=get("THEMI_PUBLIC_URL").rstrip("/"),
            telegram_bot_token=Secret(token) if token else None,
            telegram_api_url=telegram_url.rstrip("/"),
            log_level=level,  # type: ignore[arg-type]  # validated above
            tool_routing=routing,  # type: ignore[arg-type]  # validated above
            conversation_mode=rollout,  # type: ignore[arg-type]  # validated above
            http_host=get("THEMI_HTTP_HOST") or "127.0.0.1",
            http_port=int(port_text),
            telegram_enabled=get("THEMI_DISABLE_TELEGRAM").lower() not in ("1", "true", "yes"),
            control_dir=Path(control) if (control := get("THEMI_CONTROL_DIR")) else None,
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
            environment={k: v for k, v in values.items() if isinstance(v, str)},
        )


def key_beside_database(values: Mapping[str, str]) -> Path:
    """SP2: where Themi keeps the key it made itself: next to the database."""
    db = Path(values.get("THEMI_DB_PATH", "").strip() or "data/themi.db")
    return db.parent / "secret.key"


def ensure_secret_key(values: Mapping[str, str]) -> Path | None:
    """SP2: on a new Themi with no key set, make one next to the database (readable only
    by its owner) and return its path, so it can be told to an admin to save. Nothing is
    made when a key is set, when Themi made one already, or when there's a database
    already: data encrypted with a lost key must never meet a new one."""
    if values.get("THEMI_SECRET_KEY", "").strip() or values.get("THEMI_SECRET_KEY_FILE", ""):
        return None
    path = key_beside_database(values)
    database = Path(values.get("THEMI_DB_PATH", "").strip() or "data/themi.db")
    if path.exists() or database.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(generate_key() + "\n")
    return path


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
