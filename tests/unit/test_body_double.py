"""BD1a: the body double's own words: how long, the command, the nudge button."""

from __future__ import annotations

import pytest

from themi.core.body_double import GUIDED, SILENT, SPRINT, BodyDouble, parse_command, span_words
from themi.core.tasks import Task


def test_span_words() -> None:
    assert span_words(60) == "the hour"
    assert span_words(120) == "two hours"
    assert span_words(240) == "four hours"
    assert span_words(45) == "45 minutes"


def test_the_command() -> None:
    assert parse_command("") == ("", 0)
    assert parse_command("sprint") == (SPRINT, 0)
    assert parse_command("pomodoro") == (SPRINT, 0)
    assert parse_command("quiet 45") == (SILENT, 45)
    assert parse_command("45 minutes") == ("", 45)
    assert parse_command("step by step") == (GUIDED, 0)
    with pytest.raises(ValueError):
        parse_command("loudly")


def task(**changes: object) -> Task:
    base: dict = {
        "id": 1, "title": "Do the taxes", "kind": "text", "effort": 4, "assignee": 1,
        "default_owner": 1, "assign_reason": "", "status": "open", "due_on": None,
    }  # fmt: skip
    return Task(**{**base, **changes})


def test_body_double_on_bigger_jobs_only() -> None:
    offer = BodyDouble.nudge_buttons
    assert [b.label for b in offer(None, task())] == ["Body double"]  # type: ignore[arg-type]
    assert offer(None, task(effort=1)) == []  # type: ignore[arg-type]
    assert [b.label for b in offer(None, task(effort=1, steps=("a", "b")))] == ["Body double"]  # type: ignore[arg-type]
    assert offer(None, task(medicine=True)) == []  # type: ignore[arg-type]
    assert offer(None, task(check_in=True)) == []  # type: ignore[arg-type]
