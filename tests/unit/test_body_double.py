"""BD1a: the body double's own words: how long, the command, the nudge button."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from themi.channels.mini_app import check_init_data, sign_init_data
from themi.core.body_double import GUIDED, SILENT, SPRINT, BodyDouble, parse_command, span_words
from themi.core.body_double_guided import is_optional, proposed_steps
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


# ----- BD1b ---------------------------------------------------------------------------------


def test_proposed_steps_are_trimmed_capped_and_tagged() -> None:
    data = {
        "steps": [
            {"text": "  Clear   the counter. ", "optional": False},
            {"text": "", "optional": False},
            {"text": "Wipe the shelves", "optional": True},
            {"text": "Dust the fan (Optional/Bonus)", "optional": True},
        ]
        + [{"text": f"Step {n}", "optional": False} for n in range(20)]
    }
    steps = proposed_steps(data)
    assert steps[:3] == [
        "Clear the counter",
        "Wipe the shelves (Optional/Bonus)",
        "Dust the fan (Optional/Bonus)",  # tagged once
    ]
    assert len(steps) == 12


def test_optional_tags() -> None:
    assert is_optional("Wipe the shelves (Optional/Bonus)")
    assert is_optional("Wipe the shelves (optional)")
    assert is_optional("Polish it (bonus)")
    assert not is_optional("Optionally wipe")


def test_the_eval_checks() -> None:
    from tests.evals.test_body_double_evals import problems

    assert problems(["Wash the clothes", "Dry them", "Fold them"], ("wash", "dry", "fold")) == []
    assert problems(["Fold", "Wash"], ("wash", "fold")) == ["order ('wash', 'fold') at [1, 0]"]
    assert problems(["You should wash the clothes"], ()) == [
        "advice: 'You should wash the clothes'"
    ]


# ----- BD3a: the Mini App's initData ---------------------------------------------------------

TOKEN = "123:abc"
NOW = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)


def init_data(user_id: int = 42, at: datetime = NOW, token: str = TOKEN, **more: str) -> str:
    fields = {"auth_date": str(int(at.timestamp())), "query_id": "AAE",
              "user": json.dumps({"id": user_id, "first_name": "Erin"}), **more}  # fmt: skip
    fields["hash"] = sign_init_data(fields, token)
    return urlencode(fields)


def test_good_init_data_names_its_user() -> None:
    assert check_init_data(init_data(), TOKEN, NOW + timedelta(seconds=20)) == 42


def test_stale_init_data_is_refused() -> None:
    assert check_init_data(init_data(), TOKEN, NOW + timedelta(seconds=61)) is None


def test_forged_init_data_is_refused() -> None:
    assert check_init_data(init_data(token="999:other"), TOKEN, NOW) is None
    tampered = init_data().replace("%22id%22%3A+42", "%22id%22%3A+7")
    assert "7" in tampered and check_init_data(tampered, TOKEN, NOW) is None
    assert check_init_data("", TOKEN, NOW) is None
    assert check_init_data("not a query", TOKEN, NOW) is None
    unsigned = urlencode({"auth_date": str(int(NOW.timestamp())), "user": '{"id": 1}'})
    assert check_init_data(unsigned, TOKEN, NOW) is None
