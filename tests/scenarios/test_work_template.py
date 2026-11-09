"""CR12: the work template: one person's working day, with no household in it.
SL5: in Slack, its only chat."""

from __future__ import annotations

import re
from pathlib import Path

from tests.fakes.slack_api import MICHAEL, FakeSlack
from tests.fixtures.db import migrated_file
from tests.fixtures.family import SeededFamily
from tests.scenarios.slack_harness import SlackScenario
from themi.accounts import SYSTEM, AccountStore, Role
from themi.config import load_config, load_template, resolve_modules
from themi.settings import Settings
from themi.standard.tasks import TaskBoard
from themi.storage.secrets import Cipher, generate_key

HOUSEHOLD_WORDS = re.compile(r"\b(washer|pantry|partners?|chores?|family)\b", re.IGNORECASE)


def work_family(tmp_path: Path) -> SeededFamily:
    store = AccountStore(migrated_file(tmp_path / "work.db"), Cipher(generate_key()))
    workspace = store.create_family("Michael at work", "America/Los_Angeles", template="work")
    michael = store.create_member(SYSTEM, "Michael", Role.ADMIN)
    return SeededFamily(store, workspace, michael, michael)


def work_app(tmp_path: Path, slack: FakeSlack, env: dict[str, str] | None = None) -> SlackScenario:
    (tmp_path / "themi.toml").write_text('template = "work"\n')
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": generate_key(), **(env or {})})
    config = load_config(tmp_path / "themi.toml")
    modules = resolve_modules(config, settings)
    return SlackScenario(
        work_family(tmp_path), slack, modules, template=load_template(config.template)
    )


def said_to_the_model(scenario: SlackScenario) -> list[str]:
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
    tmp_path: Path, fake_slack: FakeSlack
) -> None:
    google = {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret"}
    scenario = work_app(tmp_path, fake_slack, google)
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


async def test_a_working_day(tmp_path: Path, fake_slack: FakeSlack) -> None:
    """Boot from themi.toml with Slack as the only chat: Michael says hello and is paired by
    his Slack email, adds a task with a due time, gets its nudge, taps Done, and the card
    changes where it is. A question in a thread is answered there; /themi runs commands."""
    scenario = work_app(tmp_path, fake_slack)
    assert list(scenario.app.channel.channels) == ["slack"]
    store = scenario.app.store
    michael = store.member_by_name("Michael")
    assert michael is not None
    store.set_email(SYSTEM, michael.id, "michael@work.test")
    scenario.use_scripted_models(michael)
    await scenario.start()
    try:
        assert await scenario.say("hello") == [
            "Hi Michael! You're connected to Themi here in Slack."
        ]
        assert store.identity(michael.id, "slack") == MICHAEL
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
        replies = await scenario.say("Remind me to send the quarterly report at 2")
        assert "I'll remind you at 2." in replies
        await scenario.advance(hours=5, minutes=1)  # 14:01
        nudge = [t for t in scenario.inbox() if "quarterly report" in t]
        assert nudge and nudge[-1].startswith("Due today: Send the quarterly report")
        assert "Done" in scenario.last_buttons()
        await scenario.tap("Done")
        board = scenario.app.services.get(TaskBoard)
        assert not any(t.title == "Send the quarterly report" for t in board.open_for(michael))
        assert fake_slack.calls("chat.update"), "the card changes where it is"

        # A question in a thread under Themi's nudge is answered in that thread.
        thread = fake_slack.posts(MICHAEL)[0]
        parent = scenario.app.db.scalar(
            "SELECT ts FROM slack_messages WHERE member_id = ? ORDER BY id DESC LIMIT 1",
            (michael.id,),
        )
        assert thread and parent
        scenario.primary.queue_text("Nothing else is due today.")
        assert await scenario.say("anything else today?", thread_ts=parent) == [
            "Nothing else is due today."
        ]
        assert fake_slack.posts(MICHAEL)[-1]["thread_ts"] == parent

        # /themi site: a command, run through the agent, its link sent back in Slack.
        site = await scenario.command("site")
        assert site and "http://themi.test/login/" in site[-1]
    finally:
        await scenario.stop()


def test_the_modules_page_sets_up_work(tmp_path: Path) -> None:
    """SP8a: what the wizard's work run checked, the Modules page's way: the work template
    chosen, Google's client id and secret given, and the config it makes."""
    from themi.config import available_modules, parse_config, write_config
    from themi.modules.planning import Planner
    from themi.storage.secrets import Secret, generate_key

    planner = Planner(parse_config({}), available_modules(), lambda n: load_template(n).modules)
    planner.use_template("work")
    planner.draft.sections["google"] = {"client_id": "id"}
    toml_path = tmp_path / "themi.toml"
    write_config(planner.as_config(), toml_path)
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": generate_key()})
    stored = {"google": {"client_secret": Secret("secret")}}
    config = load_config(toml_path)
    assert config.template == "work"
    names = [m.name for m in resolve_modules(config, settings, stored=stored)]
    assert {"tasks", "gmail", "calendar", "google_tasks"} <= set(names)
    assert "groceries" not in names and "liaison" not in names
