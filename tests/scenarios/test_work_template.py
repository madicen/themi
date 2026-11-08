"""CR12: the work template: one person's working day, with no household in it."""

from __future__ import annotations

import re
from pathlib import Path

from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi.accounts import SYSTEM, AccountStore, Role
from themi.config import load_config, load_template, resolve_modules
from themi.core.tasks import TaskBoard
from themi.settings import Settings
from themi.setup_wizard import run_setup
from themi.storage import open_database
from themi.storage.secrets import Cipher, generate_key

HOUSEHOLD_WORDS = re.compile(r"\b(washer|pantry|partners?|chores?|family)\b", re.IGNORECASE)
MICHAEL_TELEGRAM_ID = 7001


def work_family(tmp_path: Path) -> SeededFamily:
    store = AccountStore(open_database(tmp_path / "work.db"), Cipher(generate_key()))
    workspace = store.create_family("Michael at work", "America/Los_Angeles", template="work")
    michael = store.create_member(SYSTEM, "Michael", Role.ADMIN)
    return SeededFamily(store, workspace, michael, michael)


def work_app(tmp_path: Path, telegram: FakeTelegram, env: dict[str, str] | None = None) -> Scenario:
    (tmp_path / "themi.toml").write_text('template = "work"\n')
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": generate_key(), **(env or {})})
    config = load_config(tmp_path / "themi.toml")
    modules = resolve_modules(config, settings)
    return Scenario(
        work_family(tmp_path), telegram, modules=modules, template=load_template(config.template)
    )


def said_to_the_model(scenario: Scenario) -> list[str]:
    """The system prompt and every description of the tools it can be sent."""
    tools = scenario.app.services.tools
    texts = [scenario.app.services.system_text()]
    for spec in tools.specs():
        texts.append(spec.description)
        texts += [
            p.get("description", "") for p in spec.input_schema.get("properties", {}).values()
        ]
    return texts


def test_the_work_template_says_nothing_about_a_household(
    tmp_path: Path, fake_telegram: FakeTelegram
) -> None:
    google = {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret"}
    scenario = work_app(tmp_path, fake_telegram, google)
    names = [m for m in scenario.app.services.tools.group_names()]
    assert {"calendar", "email"} <= set(names) and "recipes" not in names
    found = {
        w.lower() for text in said_to_the_model(scenario) for w in HOUSEHOLD_WORDS.findall(text)
    }
    assert found == set(), f"household words sent to the model: {sorted(found)}"
    assert scenario.app.services.system_text().startswith("You are Themi, a work assistant")


def test_every_rewording_names_something_that_exists() -> None:
    from themi.config import all_groups, available_modules
    from themi.core.prompts import CORE_RULES

    template = load_template("work")
    keys = {f.key for f in CORE_RULES}
    for cls in available_modules().values():
        import inspect

        module = inspect.getmodule(cls)
        for value in vars(module).values():
            if isinstance(value, tuple) and value and hasattr(value[0], "key"):
                keys |= {f.key for f in value}
    assert set(template.prompt) <= keys
    assert set(template.groups) <= {g.name for g in all_groups()}
    every_tool = {t for g in all_groups() for t in g.tools} | {
        "create_task", "update_task", "propose_rule", "remember_fact", "reschedule_task",
        "skip_round", "snooze_task",
    }  # fmt: skip
    assert set(template.tools) <= every_tool


async def test_a_working_day(tmp_path: Path, fake_telegram: FakeTelegram) -> None:
    """Boot from themi.toml, pair Michael, add a task with a due time, get its nudge, done."""
    scenario = work_app(tmp_path, fake_telegram)
    await scenario.start()
    try:
        store = scenario.app.store
        michael = store.member_by_name("Michael")
        assert michael is not None
        code = store.create_invite(SYSTEM, michael.id)
        fake_telegram.send_text(MICHAEL_TELEGRAM_ID, f"/start {code}")
        await scenario.app.channel.poll_once()
        assert store.get_member(michael.id).telegram_user_id == MICHAEL_TELEGRAM_ID
        scenario.primary.queue_tool_call(
            "create_task",
            {
                "title": "Send the quarterly report",
                "kind": "text",
                "effort": 1,
                "due_date": "2026-10-21",
                "due_time": "14:00",
                "from_time": "",
                "assign_to": "me",
                "steps": [],
                "check_in": False,
                "importance": "normal",
            },
        )
        scenario.primary.queue_text("I'll remind you at 2.")
        await scenario.say("Michael", "Remind me to send the quarterly report at 2")
        await scenario.advance(hours=5, minutes=1)  # 14:01
        nudge = [t for t in scenario.inbox("Michael") if "quarterly report" in t]
        assert nudge and nudge[-1].startswith("Due today: Send the quarterly report")
        assert "Done" in scenario.last_buttons("Michael")
        await scenario.tap("Michael", "Done")
        board = scenario.app.services.get(TaskBoard)
        assert not any(t.title == "Send the quarterly report" for t in board.open_for(michael))
    finally:
        await scenario.stop()


def test_the_wizard_sets_up_work(tmp_path: Path) -> None:
    import tomllib

    answers = {"Which template": "work", "Google OAuth client id": "id"}

    def ask(question: str, default: str | None = None) -> str:
        return next((v for k, v in answers.items() if k in question), "")

    def secret(question: str) -> str:
        return "secret" if "Google OAuth client secret" in question else ""

    def skip(coro):
        coro.close()

    toml_path, env_path = run_setup(ask, secret, lambda _: None, tmp_path, run=skip)
    assert tomllib.loads(toml_path.read_text())["template"] == "work"
    env = dict(line.split("=", 1) for line in env_path.read_text().splitlines())
    names = [m.name for m in resolve_modules(load_config(toml_path), Settings.from_mapping(env))]
    assert {"tasks", "gmail", "calendar", "google_tasks"} <= set(names)
    assert "groceries" not in names and "liaison" not in names
