"""MP5: a module's household settings and preferences as a plain form on its Modules page.

The Settings and Family pages have hand-written forms for these (several modules' fields
side by side); a module's own page shows its models field by field instead, each saved on
its own through the account store, as those pages save them.

How a field shows: a bool is a checkbox; an int a whole number (`*_cents` as dollars); a
float a number; a time a time picker; a tuple of words one per line; a `Literal` a choice;
the rest text. The label is the field's `title`, else its name in words; its `description`
is the hint under it.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from datetime import time
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from themi.accounts import InvalidValue
from themi.accounts.setup import parse_money_to_cents

Kind = Literal["bool", "number", "decimal", "money", "time", "lines", "choice", "text"]


@dataclass(frozen=True)
class Input:
    name: str
    label: str
    kind: Kind
    value: Any  # as the form shows it: "12.50", "07:15", "a\nb", True
    hint: str = ""
    choices: tuple[str, ...] = ()
    optional: bool = False  # blank means off (an optional time)


def _bare(annotation: Any) -> tuple[Any, bool]:
    """The annotation without `| None`, and whether None was allowed."""
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _kind(name: str, annotation: Any) -> tuple[Kind, tuple[str, ...]]:
    if annotation is bool:
        return "bool", ()
    if annotation is int:
        return ("money" if name.endswith("_cents") else "number"), ()
    if annotation is float:
        return "decimal", ()
    if annotation is time:
        return "time", ()
    if get_origin(annotation) is tuple:
        return "lines", ()
    if get_origin(annotation) is Literal:
        return "choice", tuple(str(a) for a in get_args(annotation))
    return "text", ()


def label_of(name: str) -> str:
    words = name.removesuffix("_cents").replace("_", " ").strip()
    return words[:1].upper() + words[1:] + (" ($)" if name.endswith("_cents") else "")


def inputs(model: type[BaseModel], current: BaseModel, shown: set[str] | None) -> list[Input]:
    out = []
    for name, info in model.model_fields.items():
        if shown is not None and name not in shown:
            continue
        annotation, optional = _bare(info.annotation)
        kind, choices = _kind(name, annotation)
        value = getattr(current, name)
        if kind == "money":
            shown_value: Any = f"{value / 100:.2f}"
        elif kind == "time":
            shown_value = value.strftime("%H:%M") if isinstance(value, time) else (value or "")
        elif kind == "lines":
            shown_value = "\n".join(str(v) for v in value)
        elif kind == "bool":
            shown_value = bool(value)
        else:
            shown_value = "" if value is None else str(value)
        out.append(
            Input(
                name,
                info.title or label_of(name),
                kind,
                shown_value,
                info.description or "",
                choices,
                optional,
            )
        )
    return out


def parse(model: type[BaseModel], form: dict[str, Any], shown: set[str] | None) -> dict[str, Any]:
    """The changes a form makes, for `save_preferences` / `save_household`. A checkbox left
    unticked is False; an empty number is left as it was; an empty optional time is off."""
    values: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        if shown is not None and name not in shown:
            continue
        annotation, optional = _bare(info.annotation)
        kind, _ = _kind(name, annotation)
        raw = form.get(name)
        if kind == "bool":
            values[name] = raw == "on"
            continue
        if raw is None:
            continue
        text = str(raw).strip()
        if kind == "money":
            values[name] = parse_money_to_cents(text) if text else None
        elif kind == "number":
            values[name] = _number(text, int)
        elif kind == "decimal":
            values[name] = _number(text, float)
        elif kind == "lines":
            values[name] = tuple(line.strip() for line in text.splitlines() if line.strip())
        elif kind == "time" and not text:
            values[name] = "" if optional else None  # "" turns an optional time off
        else:
            values[name] = text
    return values


def _number(text: str, cast: type[int] | type[float]) -> int | float | None:
    if not text:
        return None
    try:
        return cast(text)
    except ValueError as exc:
        raise InvalidValue(f"{text!r} isn't a number") from exc
