"""D5b: the control panel drives `make dev`'s fakes, through the simulator, and Themi looks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fakes.wiring import wall_list
from tests.fixtures.dev import Boot, DevRun
from tools.dev.controls import SECTIONS, ControlPanel
from tools.dev.fakes import DevFakes
from tools.dev.simulator import Simulator


@dataclass
class Panel:
    run: DevRun
    sim: Simulator
    client: httpx.AsyncClient

    async def act(self, section: str, action: str, **values: Any) -> httpx.Response:
        return await self.client.post(
            "/control/act", json={"section": section, "action": action, "values": values}
        )

    async def ok(self, section: str, action: str, **values: Any) -> str:
        response = await self.act(section, action, **values)
        assert response.status_code == 200, response.text
        return response.json()["happened"]

    def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        return self.run.runtime.app.db.query(sql, params)

    def device_state(self, name: str) -> str:
        (row,) = self.rows(
            "SELECT s.state FROM device_states s JOIN devices d ON d.id = s.device_id "
            "WHERE d.name = ?",
            name,
        )
        return row["state"]


@pytest.fixture
async def panel(boot: Boot) -> AsyncIterator[Panel]:
    run = await boot()
    sim = Simulator()
    sim.start()
    sim.controls = ControlPanel(run.fakes)
    # Async, so Themi's loop (this test's) is free to make each change while we wait.
    async with httpx.AsyncClient(base_url=sim.url, timeout=30) as client:
        yield Panel(run, sim, client)
    sim.stop()


def test_every_fake_has_a_section_but_travel(tmp_path: Path) -> None:
    driven = {name for section in SECTIONS for name in section.uses}
    assert driven == set(DevFakes(tmp_path / "fakes.json").held()) - {"travel"}  # D5c


async def test_the_schema_and_page(panel: Panel) -> None:
    schema = (await panel.client.get("/control/schema")).json()["sections"]
    assert [s["title"] for s in schema] == [s.title for s in SECTIONS]
    email = schema[0]["actions"][0]
    assert email["label"] == "Send a ready-made email"
    assert email["fields"][0] == {
        "name": "person",
        "label": "Who",
        "kind": "select",
        "options": ["Erin", "Husband"],
        "default": "Erin",
        "required": True,
    }
    page = (await panel.client.get("/control")).text
    assert "/control/schema" in page and "/control/act" in page
    assert 'href="/control"' in (await panel.client.get("/")).text  # linked from the chat


async def test_an_email_arrives_and_is_read_in(panel: Panel) -> None:
    happened = await panel.ok("email", "preset", person="Husband", preset="A school notice")
    assert (
        happened
        == 'Email: "Field trip permission slip due Thursday" from Maple Elementary to Husband'
    )
    (row,) = panel.rows("SELECT subject, from_address FROM emails")
    assert row["from_address"] == "office@maple.example"

    await panel.ok(
        "email",
        "custom",
        person="Erin",
        sender="Shop <deals@shop.example>",
        subject="Sale",
        text="20% off",
        tab="Promotions",
    )
    (sale,) = panel.rows("SELECT labels FROM emails WHERE subject = 'Sale'")
    assert "CATEGORY_PROMOTIONS" in sale["labels"]


async def test_calendar_events_are_added_moved_and_cancelled(panel: Panel) -> None:
    await panel.ok(
        "calendar", "add", person="Erin", title="Dentist", date="2026-10-22", start="10:00",
        minutes="45", place="Smile Dental",
    )  # fmt: skip
    events = panel.run.fakes.gcal.calendars["erin@gmail.com"]["primary"].events
    (event,) = events.values()
    assert event["start"]["dateTime"] == "2026-10-22T10:00:00-07:00"
    assert event["end"]["dateTime"] == "2026-10-22T10:45:00-07:00"
    assert event["location"] == "Smile Dental"

    await panel.ok(
        "calendar", "move", person="Erin", title="dentist", date="2026-10-23", start="15:00"
    )
    assert event["start"]["dateTime"] == "2026-10-23T15:00:00-07:00"
    assert event["end"]["dateTime"] == "2026-10-23T15:45:00-07:00"  # as long as before
    await panel.ok("calendar", "cancel", person="Erin", title="Dentist")
    assert event["status"] == "cancelled"


async def test_said_to_a_speaker_and_changed_in_keep(panel: Panel) -> None:
    fakes = panel.run.fakes
    await panel.ok("home", "task", person="Erin", text="Call the plumber")
    assert fakes.gtasks.has_list("erin@gmail.com", "My Tasks")
    await panel.ok("home", "keep", person="Erin", text="oat milk")
    groceries = "SELECT status FROM grocery_list WHERE name LIKE '%oat milk%'"
    assert [r["status"] for r in panel.rows(groceries)] == ["needed"]
    await panel.ok("home", "keep_tick", person="Erin", text="Oat milk")
    assert fakes.keep.checked_texts("erin@gmail.com") == ["oat milk"]
    assert [r["status"] for r in panel.rows(groceries)] == ["bought"]


async def test_the_wall_to_do_becomes_a_task_and_its_tick_closes_it(panel: Panel) -> None:
    await panel.ok("wall", "add", title="Fix the gate", person="Husband")
    (task,) = panel.rows("SELECT status FROM tasks WHERE title = 'Fix the gate'")
    assert task["status"] == "open"
    await panel.ok("wall", "add", title="Sort photos", person="Nobody")
    await panel.ok("wall", "top", title="Fix the gate")
    assert panel.run.fakes.cozyla.wall_order(wall_list(panel.run.fakes.cozyla))[0] == "Fix the gate"
    await panel.ok("wall", "tick", title="fix the gate")
    (task,) = panel.rows("SELECT status FROM tasks WHERE title = 'Fix the gate'")
    assert task["status"] == "done"


async def test_ourgroceries_changes_come_in(panel: Panel) -> None:
    eggs = "SELECT status FROM grocery_list WHERE name = 'eggs'"
    await panel.ok("groceries", "add", item="Eggs")
    assert [r["status"] for r in panel.rows(eggs)] == ["needed"]
    await panel.ok("groceries", "cross", item="eggs")
    assert [r["status"] for r in panel.rows(eggs)] == ["bought"]


async def test_the_devices_are_read_at_once(panel: Panel) -> None:
    assert await panel.ok("laundry", "state", machine="Washer", state="Running") == (
        "Laundry (LG): Washer: running"
    )
    assert panel.device_state("Washer") == "running"
    await panel.ok("dishwasher", "state", state="Running", minutes="80")
    assert panel.run.fakes.home_connect.seconds_left["BOSCH-SMV-1"] == 4800
    assert panel.device_state("Dishwasher") == "Run"
    await panel.ok("vacuum", "status", status="Trapped", room="Kitchen")
    assert panel.device_state("Robbie") != "docked"
    await panel.ok("vacuum", "part", part="filter", how="Worn out")
    assert panel.run.fakes.roborock.parts["rr-duid-1"]["filter_work_time"] == 540_000


async def test_energy_signals_are_recorded(panel: Panel) -> None:
    assert await panel.ok("energy", "day", person="Erin", level="Low") == (
        "Energy (dev only): Erin: day_level -1.0 (control panel)"
    )
    rows = panel.rows("SELECT source, value FROM energy_signals")
    assert [(r["source"], r["value"]) for r in rows] == [("day_level", -1.0)]


async def test_each_action_is_in_the_transcript_and_the_report(panel: Panel) -> None:
    await panel.ok("groceries", "add", item="Bread")
    (notice,) = [e for e in panel.sim.transcript(0) if e.text.startswith("⚙")]
    assert notice.text == '⚙ OurGroceries: "Bread" added in the app'
    assert '-- ⚙ OurGroceries: "Bread" added in the app --' in panel.sim.report()


async def test_mistakes_are_said_and_change_nothing(panel: Panel) -> None:
    missing = await panel.act("groceries", "add", item=" ")
    assert (missing.status_code, missing.json()["error"]) == (400, "Item is needed")
    unknown = await panel.act("wall", "tick", title="Nothing like it")
    assert unknown.json()["error"] == "the wall's list has no open 'Nothing like it'"
    bad_choice = await panel.act("laundry", "state", machine="Toaster", state="Running")
    assert bad_choice.json()["error"] == "Machine can't be 'Toaster'"
    assert (await panel.act("nope", "nope")).status_code == 400
    assert not [e for e in panel.sim.transcript(0) if e.text.startswith("⚙")]


async def test_the_state_shows_what_the_fakes_hold(panel: Panel) -> None:
    await panel.ok("wall", "add", title="Fix the gate", person="Husband")
    state = (await panel.client.get("/control/state")).json()
    assert set(state) == {s.id for s in SECTIONS}
    assert state["wall"][0] == "Family list: Fix the gate (Husband)"
    assert state["laundry"][:2] == ["Washer: POWER_OFF", "Dryer: INITIAL"]
    assert state["email"][0] == "Erin (erin@gmail.com): 0 in the inbox, 0 unread"


async def test_without_fakes_the_panel_says_so() -> None:
    sim = Simulator()
    sim.start()
    try:
        async with httpx.AsyncClient(base_url=sim.url) as client:
            schema = (await client.get("/control/schema")).json()
            assert schema["sections"] == [] and "FAKES=0" in schema["error"]
            assert (await client.post("/control/act", json={})).status_code == 404
    finally:
        sim.stop()


async def test_while_themi_starts_the_page_is_told_to_wait() -> None:
    sim = Simulator()
    sim.controls_coming = True
    sim.start()
    try:
        async with httpx.AsyncClient(base_url=sim.url) as client:
            schema = (await client.get("/control/schema")).json()
            assert schema["retry"] and "still starting" in schema["error"]
            assert (await client.post("/control/act", json={})).status_code == 503
    finally:
        sim.stop()
