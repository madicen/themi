"""C1a: Themi's own client for Cozyla's unofficial cloud API, against the fake."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tests.fakes.cozyla import EMAIL, PASSWORD, FakeCozyla
from themi import clock
from themi.connectors.cozyla import CozylaClient, CozylaConfig, CozylaError
from themi.storage.secrets import Secret


def client_for(
    fake: FakeCozyla, password: str = PASSWORD, todo_list: str = "Family"
) -> CozylaClient:
    config = CozylaConfig(EMAIL, Secret(password), todo_list=todo_list)
    return CozylaClient(config, password_key=fake.public_key, transport=fake.transport)


async def test_signs_in_once_with_the_password_encrypted(fake_cozyla: FakeCozyla) -> None:
    fake_cozyla.add_member("Erin")
    fake_cozyla.add_list("Family")
    client = client_for(fake_cozyla)
    (erin,) = await client.members()
    (family,) = await client.lists()
    assert (erin.id, erin.name) == ("m-erin", "Erin")
    assert family.title == "Family"
    assert fake_cozyla.paths() == [
        "users/cozUsers/signIn",
        "users/cozUsersMember/queryMembers",
        "rewards/todosList/list",
    ]
    sign_in, *calls = fake_cozyla.calls
    assert sign_in.body["email"] == EMAIL and sign_in.body["loginClient"] == "DEVICE"
    assert sign_in.body["deviceSn"] == "themi"
    assert all(PASSWORD not in json.dumps(c.body) for c in fake_cozyla.calls)
    token = calls[0].headers["authorization"]
    assert not token.startswith("Bearer") and token in fake_cozyla.tokens
    assert all(c.body["deviceUid"] == "dev-1" for c in calls)
    assert "x-device-info" in sign_in.headers


async def test_an_expired_token_means_one_new_sign_in_never_a_loop(
    fake_cozyla: FakeCozyla,
) -> None:
    client = client_for(fake_cozyla)
    await client.lists()
    fake_cozyla.expire_tokens()
    await client.lists()
    assert fake_cozyla.paths().count("users/cozUsers/signIn") == 2

    fake_cozyla.fail("todosList/list", code=101, times=2)
    with pytest.raises(CozylaError) as caught:
        await client.lists()
    assert caught.value.code == 101
    assert fake_cozyla.paths().count("users/cozUsers/signIn") == 3  # just the one retry


async def test_a_wrong_password_or_a_lockout_is_explained(
    fake_cozyla: FakeCozyla, frozen_clock: datetime
) -> None:
    with pytest.raises(CozylaError, match="email or password"):
        await client_for(fake_cozyla, "nope").lists()

    fake_cozyla.locked_for = 600
    client = client_for(fake_cozyla)
    with pytest.raises(CozylaError, match="10 minutes"):
        await client.lists()
    tries = len(fake_cozyla.calls)
    with pytest.raises(CozylaError, match="10 minutes"):
        await client.lists()  # still locked: not even asked
    assert len(fake_cozyla.calls) == tries
    fake_cozyla.locked_for = 0
    clock.advance(timedelta(minutes=10))
    await client.lists()


async def test_errors_and_outages_become_cozyla_errors(fake_cozyla: FakeCozyla) -> None:
    client = client_for(fake_cozyla)
    fake_cozyla.fail("todosInfo/list", code=500)
    with pytest.raises(CozylaError, match="500"):
        await client.todos()

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    config = CozylaConfig(EMAIL, Secret(PASSWORD))
    offline = CozylaClient(config, transport=httpx.MockTransport(down))
    with pytest.raises(CozylaError, match="couldn't be reached"):
        await offline.lists()


async def test_to_dos_are_read_and_changed(fake_cozyla: FakeCozyla) -> None:
    family = fake_cozyla.add_list("Family")
    due = datetime(2026, 10, 27, 7, tzinfo=UTC)
    vet = fake_cozyla.add_todo(family, "Call the vet", assignee="m-erin", due=due)
    fake_cozyla.edit(vet, todoStars=3, isFlag=1, reminderTime=30, timeUnit="minutes_before_30")
    fake_cozyla.add_todo(family, "Old thing", done=True)
    client = client_for(fake_cozyla)

    todos = {t.title: t for t in await client.todos()}
    assert todos["Call the vet"].due == due and todos["Call the vet"].assignee == "m-erin"
    assert not todos["Call the vet"].completed and todos["Old thing"].completed
    assert todos["Old thing"].due is None and todos["Old thing"].list_id == str(family)

    await client.update(todos["Call the vet"], title="Call the vet back", assignee=None, due=None)
    changed = fake_cozyla.todos[vet]
    assert changed["todoTitle"] == "Call the vet back" and changed["assignMemberUid"] is None
    assert changed["dueDateTime"] == -1
    assert (changed["todoStars"], changed["isFlag"], changed["timeUnit"]) == (
        3,
        1,
        "minutes_before_30",
    )  # what Themi doesn't know about is sent back as it was

    new_id = await client.create(str(family), "Buy stamps", assignee="m-erin", due=due)
    assert fake_cozyla.todos[int(new_id)]["dueDateTime"] == int(due.timestamp() * 1000)
    await client.set_done(new_id, True)
    assert fake_cozyla.titles(family, done=True) == ["Buy stamps", "Old thing"]
    await client.delete(new_id)
    assert int(new_id) not in fake_cozyla.todos


# ----- themi cozyla check ------------------------------------------------------------


async def test_the_check_shows_what_is_there_without_titles_or_changes(
    fake_cozyla: FakeCozyla,
) -> None:
    from themi.connectors.cozyla.check import check

    fake_cozyla.add_member("Erin")
    fake_cozyla.add_member("Michael")
    family = fake_cozyla.add_list("Family")
    fake_cozyla.add_list("Groceries")
    fake_cozyla.add_todo(family, "Call the vet", due=datetime(2026, 10, 27, 7, tzinfo=UTC))
    fake_cozyla.add_todo(family, "Old thing", done=True)
    config = CozylaConfig(EMAIL, Secret(PASSWORD), todo_list="family")
    client = CozylaClient(
        config,
        timezone="America/Los_Angeles",
        password_key=fake_cozyla.public_key,
        transport=fake_cozyla.transport,
    )

    report = await check(client)
    assert "Members: Erin, Michael" in report
    assert "  Family: 1 open, 1 done  <- COZYLA_TODO_LIST" in report
    assert "  Groceries: 0 open, 0 done" in report
    assert "Due dates as stored (America/Los_Angeles): Tue 27 Oct 00:00" in report
    assert "Call the vet" not in report
    assert not [p for p in fake_cozyla.paths() if p.rsplit("/", 1)[-1] in WRITES]

    assert "Open on family: Call the vet" in await check(client, titles=True)


async def test_the_check_says_when_the_list_is_missing_or_unset(fake_cozyla: FakeCozyla) -> None:
    from themi.connectors.cozyla.check import check

    fake_cozyla.add_list("Family")
    unset = client_for(fake_cozyla, todo_list="")
    assert "COZYLA_TODO_LIST isn't set, so nothing syncs" in await check(unset)
    wrong = client_for(fake_cozyla, todo_list="Chores")
    assert "COZYLA_TODO_LIST is 'Chores', which isn't one of the lists" in await check(wrong)


WRITES = {"create", "update", "checkTodo", "delete"}


async def test_chores_round_trip_every_field(fake_cozyla: FakeCozyla) -> None:
    """C2a: update/v1 keeps nothing that isn't sent, so every field goes each time."""
    from datetime import date

    from themi.connectors.cozyla import WallSchedule

    clock.freeze(datetime(2026, 10, 21, 16, tzinfo=UTC))
    fake_cozyla.add_member("Erin")
    client = client_for(fake_cozyla)
    weekly = WallSchedule(True, "Weekly", 1, "Wednesday", start=date(2026, 10, 21))
    made = await client.create_chore("Bring bins in", ["m-erin"], "Everyone", weekly)
    assert made.members == ("m-erin",) and made.schedule.days == "Wednesday"
    assert fake_cozyla.chores[made.uid]["reminder"] == -1  # Themi does the reminding
    await client.update_chore(made, "Bring the bins in", ["m-erin"], "Everyone", weekly)
    (chore,) = await client.chores()
    assert chore.name == "Bring the bins in" and chore.schedule == made.schedule

    (record,) = await client.chore_records(date(2026, 10, 21))
    assert (record.member, record.status) == ("m-erin", "pending")
    await client.check_chore(made.uid, "m-erin", date(2026, 10, 21), True)
    (record,) = await client.chore_records(date(2026, 10, 21))
    assert record.status == "completed"
    assert await client.chore_records(date(2026, 10, 22)) == []
    await client.delete_chore(made.uid)
    assert await client.chores() == []


async def test_routines_and_their_records(fake_cozyla: FakeCozyla) -> None:
    from datetime import date

    from themi.connectors.cozyla import WallSchedule

    clock.freeze(datetime(2026, 10, 21, 16, tzinfo=UTC))
    client = client_for(fake_cozyla)
    daily = WallSchedule(True, "Daily", start=date(2026, 10, 21))
    routine_id = await client.create_routine("m-erin", "Walk dog", "Morning", daily)
    (routine,) = await client.routines()
    assert (routine.id, routine.member, routine.part) == (routine_id, "m-erin", "Morning")
    await client.update_routine(routine, "Walk the dog", "Morning", daily, date(2026, 10, 21))
    (record,) = await client.routine_records(date(2026, 10, 21))
    assert (record.title, record.completed) == ("Walk the dog", False)
    await client.check_routine(routine_id, date(2026, 10, 21), True)
    (record,) = await client.routine_records(date(2026, 10, 21))
    assert record.completed
    await client.delete_routine(routine_id, date(2026, 10, 21))
    assert await client.routines() == []
