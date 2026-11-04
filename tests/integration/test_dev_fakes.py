"""D5a: `make dev` with the fakes, linked on the first run and kept between runs."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from tests.fakes.wiring import wall_list
from tests.fixtures.dev import Boot
from tools.dev import runner


async def test_the_first_run_links_everything_and_the_next_doesnt_again(boot: Boot) -> None:
    first = await boot()
    assert first.linked == [
        "Google (erin@gmail.com)",
        "Google (husband@gmail.com)",
        "Keep",
        "the wall",
        "OurGroceries",
        "Washer",
        "Dryer",
        "Robbie",
        "Cat Feeder",
        "Mochi's feeder",
        "CatGenie",
        "Dishwasher",
        "the Safeway helper",
    ]
    assert first.count("SELECT COUNT(*) FROM linked_accounts WHERE watched = 1") == 2
    assert first.count("SELECT COUNT(*) FROM keep_accounts") == 2
    assert first.count("SELECT COUNT(*) FROM devices") == 7
    assert not first.fakes.restored
    refresh_tokens = set(first.fakes.google.state.refresh_tokens)

    second = await boot()
    assert second.fakes.restored
    assert second.linked == first.linked
    assert second.count("SELECT COUNT(*) FROM linked_accounts") == 2
    assert second.count("SELECT COUNT(*) FROM devices") == 7
    assert set(second.fakes.google.state.refresh_tokens) == refresh_tokens  # no new links


async def test_after_a_restart_the_links_still_work(boot: Boot) -> None:
    await boot()
    again = await boot()
    again.fakes.gmail.deliver(
        "erin@gmail.com", sender="School <office@school.example>", subject="Trip", text="Friday"
    )
    await again.fakes.check_now("gmail.poll")  # its refresh token is still good
    assert again.count("SELECT COUNT(*) FROM emails WHERE subject = 'Trip'") == 1
    again.runtime.app.db.execute("DELETE FROM device_states")
    await again.fakes.check_now("devices.thinq")  # and LG's token: both machines are read
    lg_states = (
        "SELECT COUNT(*) FROM device_states s JOIN devices d ON d.id = s.device_id "
        "WHERE d.provider = 'lg_thinq'"
    )
    assert again.count(lg_states) == 2


async def test_the_wall_keeps_what_it_had_so_nothing_is_closed(boot: Boot) -> None:
    first = await boot()
    first.fakes.cozyla.add_todo(wall_list(first.fakes.cozyla), "Call the vet")
    await first.fakes.check_now("cozyla.sync")
    open_tasks = "SELECT COUNT(*) FROM tasks WHERE title = 'Call the vet' AND status = 'open'"
    assert first.count(open_tasks) == 1

    second = await boot()
    await second.fakes.check_now("cozyla.sync")
    assert second.count(open_tasks) == 1  # a forgetful wall would have looked like a delete
    assert second.fakes.cozyla.titles(wall_list(second.fakes.cozyla)) == ["Call the vet"]


async def test_act_makes_changes_on_themis_loop_and_checks(boot: Boot) -> None:
    run = await boot()
    loop_thread = threading.get_ident()
    seen: list[int] = []

    def change() -> str:
        seen.append(threading.get_ident())
        return run.fakes.keep.put("erin@gmail.com", "oat milk")

    item = await asyncio.to_thread(run.fakes.act, change, "groceries.keep")
    assert seen == [loop_thread] and item.startswith("item-")
    assert run.count("SELECT COUNT(*) FROM grocery_list WHERE name LIKE '%oat milk%'") == 1
    assert "oat milk" in (run.fakes.path.read_text())  # saved after the change
    with pytest.raises(RuntimeError, match="for other threads"):
        run.fakes.act(change)


def test_the_banner_lists_the_fakes(tmp_path: Path) -> None:
    result = runner.SeedResult(seeded=False, key_set=True)
    banner = runner._banner("u", "link", result, tmp_path, fakes=["Keep", "Washer"])
    assert "Fakes:    Keep; Washer" in banner and "FAKES=0" in banner
    assert "Fakes:" not in runner._banner("u", "link", result, tmp_path)


def test_no_fakes_runs_without_them(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[bool] = []
    monkeypatch.setattr(runner, "run", lambda *, fakes=True: runs.append(fakes))
    runner.main([])
    runner.main(["--no-fakes"])
    assert runs == [True, False]
