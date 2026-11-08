"""Fakes that can be saved and brought back (D5a), so `make dev` keeps what they held.

A fake lists the attributes that make up its state in `SNAPSHOT`; `snapshot()` gives
them as plain JSON and `restore()` puts them back. Call logs, injected failures, locks and
open connections aren't state, so they're left out and start empty.

The JSON is tagged for what plain JSON can't hold: tuples, sets, Counters, `count()`s,
datetimes, dicts with keys that aren't strings, and dataclasses. A dataclass comes back
only if it lives in `tests.fakes` or `themi.connectors`, so the file can't name anything
else to build (there's no pickle).
"""

from __future__ import annotations

import dataclasses
import importlib
import itertools
import json
import re
from collections import Counter
from datetime import date, datetime
from typing import Any, ClassVar

ALLOWED_MODULES = (  # CR10b2: the packs have connectors too
    "tests.fakes.",
    "themi.connectors.",
    "themi_google.connectors.",
    "themi_home.connectors.",
)
TAG = "~"


class SnapshotError(ValueError):
    pass


class Snapshots:
    SNAPSHOT: ClassVar[tuple[str, ...]] = ()

    def snapshot(self) -> dict[str, Any]:
        return {name: dump(getattr(self, name)) for name in self.SNAPSHOT}

    def restore(self, saved: dict[str, Any]) -> None:
        """Put back what `snapshot` gave; attributes it didn't save keep their values."""
        for name in self.SNAPSHOT:
            if name in saved:
                setattr(self, name, load(saved[name]))


def dump(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [dump(v) for v in value]
    if isinstance(value, tuple):
        return {f"{TAG}tuple": [dump(v) for v in value]}
    if isinstance(value, set | frozenset):  # in order, so the same set saves the same way
        return {f"{TAG}set": sorted((dump(v) for v in value), key=json.dumps)}
    if isinstance(value, Counter):
        return {f"{TAG}counter": [[dump(k), n] for k, n in value.items()]}
    if isinstance(value, dict):
        if all(isinstance(k, str) and not k.startswith(TAG) for k in value):
            return {k: dump(v) for k, v in value.items()}
        return {f"{TAG}dict": [[dump(k), dump(v)] for k, v in value.items()]}
    if isinstance(value, datetime):
        return {f"{TAG}datetime": value.isoformat()}
    if isinstance(value, date):
        return {f"{TAG}date": value.isoformat()}
    if isinstance(value, itertools.count):
        # repr is "count(7)": the next number, read without using it up.
        match = re.fullmatch(r"count\((-?\d+)\)", repr(value))
        if match is None:
            raise SnapshotError(f"only whole-number counts can be saved, not {value!r}")
        return {f"{TAG}count": int(match.group(1))}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        cls = type(value)
        return {
            f"{TAG}dataclass": f"{cls.__module__}:{cls.__qualname__}",
            "fields": {f.name: dump(getattr(value, f.name)) for f in dataclasses.fields(value)},
        }
    raise SnapshotError(f"can't save a {type(value).__name__}")


def load(data: Any) -> Any:
    if isinstance(data, list):
        return [load(v) for v in data]
    if not isinstance(data, dict):
        return data
    tags = [k for k in data if k.startswith(TAG)]
    if not tags:
        return {k: load(v) for k, v in data.items()}
    tag, body = tags[0].removeprefix(TAG), data[tags[0]]
    if tag == "tuple":
        return tuple(load(v) for v in body)
    if tag == "set":
        return {load(v) for v in body}
    if tag == "counter":
        return Counter({load(k): n for k, n in body})
    if tag == "dict":
        return {load(k): load(v) for k, v in body}
    if tag == "datetime":
        return datetime.fromisoformat(body)
    if tag == "date":
        return date.fromisoformat(body)
    if tag == "count":
        return itertools.count(int(body))
    if tag == "dataclass":
        cls = _dataclass(body)
        return cls(**{k: load(v) for k, v in data["fields"].items()})
    raise SnapshotError(f"unknown tag {tags[0]!r}")


def _dataclass(name: str) -> type:
    module_name, _, qualname = name.partition(":")
    if not module_name.startswith(ALLOWED_MODULES):
        raise SnapshotError(f"won't build {name}: not from the fakes or the connectors")
    target: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    if not (isinstance(target, type) and dataclasses.is_dataclass(target)):
        raise SnapshotError(f"{name} isn't a dataclass")
    return target
