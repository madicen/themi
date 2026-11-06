"""CM1c: scoring the sidecar's picks against `sidecar_cases.json`.

Precision (nothing made that wasn't meant) and recall (nothing meant that was missed), per
kind of item. Precision matters more: a wrong task is worse than a missed one.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CASES = Path(__file__).with_name("sidecar_cases.json")
KIND_OF = {
    "create_task": "task",
    "complete_task": "update",
    "cancel_task": "update",
    "add_calendar_event": "event",
    "remember_fact": "fact",
    "start_burnout": "mode",
    "end_burnout": "mode",
    "pause_messages": "mode",
    "resume_messages": "mode",
}


@dataclass(frozen=True)
class SidecarCase:
    id: str
    kind: str
    speaker: str
    message: str
    reply: str
    expect: tuple[dict[str, Any], ...]
    tasks: tuple[str, ...] = ()
    requires_calendar: bool = False


@dataclass
class Scored:
    case: SidecarCase
    hits: list[str] = field(default_factory=list)  # expected and made
    misses: list[str] = field(default_factory=list)  # expected, not made
    extras: list[str] = field(default_factory=list)  # made, not expected

    @property
    def passed(self) -> bool:
        return not self.misses and not self.extras


def load() -> list[SidecarCase]:
    raw = json.loads(CASES.read_text())["cases"]
    return [
        SidecarCase(
            c["id"],
            c["kind"],
            c["speaker"],
            c["message"],
            c["reply"],
            tuple(c["expect"]),
            tuple(c.get("tasks", ())),
            bool(c.get("requires_calendar", False)),
        )
        for c in raw
    ]


def _matches(want: dict[str, Any], tool: str, args: dict[str, Any], ids: dict[str, int]) -> bool:
    if want["tool"] != tool:
        return False
    if "task" in want and args.get("task_id") != ids.get(want["task"]):
        return False
    text = json.dumps(args).lower()
    return all(word.lower() in text for word in want.get("words", ()))


def score(
    case: SidecarCase, calls: Sequence[tuple[str, dict[str, Any]]], ids: dict[str, int]
) -> Scored:
    """`calls`: the tool calls that went through (outcome ok); `ids`: open task ids by title."""
    scored = Scored(case)
    left = list(calls)
    for want in case.expect:
        found = next((c for c in left if _matches(want, c[0], c[1], ids)), None)
        if found is None:
            scored.misses.append(want["tool"])
        else:
            left.remove(found)
            scored.hits.append(want["tool"])
    scored.extras = [tool for tool, _ in left]
    return scored


def summary(results: Sequence[Scored]) -> dict[str, dict[str, float | int]]:
    """Per kind: made right, made wrong, missed, and precision and recall (1.0 when there
    was nothing to measure)."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"hits": 0, "extras": 0, "misses": 0})
    for r in results:
        for tool in r.hits:
            counts[KIND_OF.get(tool, tool)]["hits"] += 1
        for tool in r.extras:
            counts[KIND_OF.get(tool, tool)]["extras"] += 1
        for tool in r.misses:
            counts[KIND_OF.get(tool, tool)]["misses"] += 1
    out: dict[str, dict[str, float | int]] = {}
    for kind, c in sorted(counts.items()):
        made = c["hits"] + c["extras"]
        meant = c["hits"] + c["misses"]
        out[kind] = {
            **c,
            "precision": round(c["hits"] / made, 2) if made else 1.0,
            "recall": round(c["hits"] / meant, 2) if meant else 1.0,
        }
    return out
