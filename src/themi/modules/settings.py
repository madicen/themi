"""CR5b: a module's own settings, read from the environment and its themi.toml section.

    class TravelSettings(ModuleSettings):
        tomtom_api_key: Secret | None = env_field("TOMTOM_API_KEY", secret=True)

Each field names the environment variable it has always been read from. A value in the
environment wins; otherwise the module's `[module.<name>]` section; otherwise the
default. A secret is read only from the environment (and .env), never from themi.toml.
Problems come back as plain lines, like the core settings' ("set both or neither").
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.fields import FieldInfo

from themi.storage.secrets import Secret

TRUE = ("1", "true", "yes", "on")


class SettingsProblem(Exception):
    """One or more problems with a module's settings, each a line for the person."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class ModuleSettings(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


def env_field(env: str, default: Any = None, *, secret: bool = False) -> Any:
    return Field(default, json_schema_extra={"env": env, "secret": secret})


def _extra(info: FieldInfo) -> dict[str, Any]:
    extra = info.json_schema_extra
    return extra if isinstance(extra, dict) else {}


def env_name(info: FieldInfo) -> str:
    return str(_extra(info).get("env", ""))


def is_secret(info: FieldInfo) -> bool:
    return bool(_extra(info).get("secret"))


def read_settings[S: ModuleSettings](
    model: type[S], env: Mapping[str, str], section: Mapping[str, Any], module: str
) -> S:
    problems = []
    values: dict[str, Any] = {}
    for key in section:
        if key not in model.model_fields:
            problems.append(f"[module.{module}] has {key}, which isn't one of its settings")
    for name, info in model.model_fields.items():
        variable = env_name(info)
        raw = env.get(variable, "").strip() if variable else ""
        if name in section and is_secret(info):
            problems.append(
                f"[module.{module}] has {name}, a secret: set {variable} in .env instead"
            )
            continue
        if raw:
            if is_secret(info):
                values[name] = Secret(raw)
            elif info.annotation is bool:
                values[name] = raw.lower() in TRUE
            else:
                values[name] = raw
        elif name in section:
            values[name] = section[name]
    if problems:
        raise SettingsProblem(problems)
    try:
        return model(**values)
    except ValidationError as exc:
        lines = []
        for error in exc.errors():
            message = str(error.get("msg", ""))
            lines.append(message.removeprefix("Value error, "))
        raise SettingsProblem(lines) from exc


def plain_values(settings: ModuleSettings) -> dict[str, Any]:
    """The settings that aren't secret, for `themi config show`."""
    return {
        name: getattr(settings, name)
        for name, info in type(settings).model_fields.items()
        if not is_secret(info)
    }
