"""CR5b: a module's own settings, read from the environment and its themi.toml section.

    class TravelSettings(ModuleSettings):
        tomtom_api_key: Secret | None = env_field("TOMTOM_API_KEY", secret=True)

Each field names the environment variable it has always been read from. A value in the
environment wins; otherwise, for a secret, the one stored on the Modules page (SP2,
encrypted in the database); otherwise the module's `[module.<name>]` section; otherwise the
default. A secret is never read from themi.toml.
Problems come back as plain lines, like the core settings' ("set both or neither").
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

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


def env_field(
    env: str,
    default: Any = None,
    *,
    secret: bool = False,
    ask: str = "",
    help: str = "",
    label: str = "",
    placeholder: str = "",
    choices: tuple[str, ...] = (),
    advanced: bool | None = None,
) -> Any:
    """A setting read from `env`. `ask`: the setup wizard's question for it (CR11); no
    question, and the wizard leaves it alone. `help`: where to get it.
    SP3a, for the Modules page: `label` (the question, by default), `placeholder`,
    `choices` (a dropdown), `advanced` (folded away; by default, a field with no question)."""
    extra = {
        "env": env,
        "secret": secret,
        "ask": ask,
        "help": help,
        "label": label,
        "placeholder": placeholder,
        "choices": list(choices),
        "advanced": advanced,
    }
    return Field(default, json_schema_extra=extra)


def _extra(info: FieldInfo) -> dict[str, Any]:
    extra = info.json_schema_extra
    return extra if isinstance(extra, dict) else {}


def env_name(info: FieldInfo) -> str:
    return str(_extra(info).get("env", ""))


def is_secret(info: FieldInfo) -> bool:
    return bool(_extra(info).get("secret"))


Source = Literal["environment", "stored", "file", "default"]


def read_settings[S: ModuleSettings](
    model: type[S],
    env: Mapping[str, str],
    section: Mapping[str, Any],
    module: str,
    stored: Mapping[str, Secret] | None = None,
) -> S:
    """`stored`: the module's secrets kept on the Modules page, by field (SP2)."""
    stored = stored or {}
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
        elif is_secret(info) and stored.get(name):
            values[name] = stored[name]
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


def questions(model: type[ModuleSettings]) -> list[tuple[str, str, str, bool, str]]:
    """CR11: what the setup wizard asks for a model: (field, env variable, question, secret,
    help), for each field with a question."""
    out = []
    for name, info in model.model_fields.items():
        extra = _extra(info)
        if extra.get("ask"):
            out.append(
                (
                    name,
                    env_name(info),
                    str(extra["ask"]),
                    is_secret(info),
                    str(extra.get("help", "")),
                )
            )
    return out


def plain_values(settings: ModuleSettings) -> dict[str, Any]:
    """The settings that aren't secret, for `themi config show`."""
    return {
        name: getattr(settings, name)
        for name, info in type(settings).model_fields.items()
        if not is_secret(info)
    }


def value_sources(
    model: type[ModuleSettings],
    env: Mapping[str, str],
    section: Mapping[str, Any],
    stored: Mapping[str, object] | None = None,
) -> dict[str, Source]:
    """SP2: where each field's value comes from, in the order `read_settings` reads them,
    for the Modules page (a field set in the environment is locked there)."""
    stored = stored or {}
    out: dict[str, Source] = {}
    for name, info in model.model_fields.items():
        variable = env_name(info)
        if variable and env.get(variable, "").strip():
            out[name] = "environment"
        elif is_secret(info) and stored.get(name):
            out[name] = "stored"
        elif name in section and not is_secret(info):
            out[name] = "file"
        else:
            out[name] = "default"
    return out


FieldKind = Literal["text", "secret", "bool", "choice", "url", "number"]


@dataclass(frozen=True)
class FieldSpec:
    """SP3a: one setting as the Modules page shows it."""

    name: str
    env: str
    label: str
    hint: str
    kind: FieldKind
    secret: bool
    choices: tuple[str, ...]
    placeholder: str
    advanced: bool
    default: Any


def fields(model: type[ModuleSettings]) -> list[FieldSpec]:
    """Each field of a settings model, with what the page needs to show it."""
    out = []
    for name, info in model.model_fields.items():
        extra = _extra(info)
        ask = str(extra.get("ask", ""))
        label = str(extra.get("label", "")) or _label_from(ask) or _label_from_name(name)
        choices = tuple(str(c) for c in extra.get("choices") or ())
        advanced = extra.get("advanced")
        out.append(
            FieldSpec(
                name=name,
                env=env_name(info),
                label=label,
                hint=str(extra.get("help", "")),
                kind=_kind(name, info, choices),
                secret=is_secret(info),
                choices=choices,
                placeholder=str(extra.get("placeholder", "")),
                advanced=bool(advanced) if advanced is not None else not ask,
                default=None if info.is_required() else info.default,
            )
        )
    return out


def _label_from(ask: str) -> str:
    """A question as a label: "Tavily API key, for web search (blank: none)" ->
    "Tavily API key, for web search"."""
    text = re.sub(r"\s*\((blank|yes or no)[^)]*\)\s*$", "", ask).strip()
    return text.removesuffix("?").strip()


def _label_from_name(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _kind(name: str, info: FieldInfo, choices: tuple[str, ...]) -> FieldKind:
    if is_secret(info):
        return "secret"
    if choices:
        return "choice"
    types = {a for a in (get_args(info.annotation) or (info.annotation,)) if a is not type(None)}
    if types == {bool}:
        return "bool"
    if types and types <= {int, float}:
        return "number"
    if name.endswith("_url"):
        return "url"
    return "text"
