"""F53: People on the wall, on Wall frames: each person's colour, and the order the people
and Together stand in. Nothing chosen is the wall as it always was."""

from __future__ import annotations

import html
import re
from dataclasses import replace

import httpx

from tests.fixtures.web import sign_in, web_client
from tests.integration.test_wall_screen import screen, wall
from tests.scenarios.harness import Scenario
from themi_home.wall_columns import TONES, WallColumns, default_layout
from themi_home.wall_view import WallView

__all__ = ["wall"]  # the fixture


def order_on(page: str) -> list[str]:
    return re.findall(r'id="col-([a-z0-9]+)"', page)


def tone_of(page: str, key: str) -> str:
    match = re.search(rf'<section class="wall-col tone-([a-z0-9]+)"[^>]*id="col-{key}">', page)
    assert match, key
    return match[1]


def keys(s: Scenario) -> tuple[str, str]:
    return f"m{s.member('Erin').id}", f"m{s.member('Husband').id}"


async def post(s: Scenario, phone: httpx.AsyncClient, csrf: str, **form: str) -> str:
    """Post People on the wall as the form stands now, with `form` on top; the flash."""
    page = (await phone.get("/wall/frames")).text
    order = re.search(r'name="order" value="([^"]*)"', page)
    assert order
    data = {"csrf": csrf, "order": order[1]}
    for key in order[1].split(","):
        chosen = re.search(
            rf'name="tone_{key}">.*?<option value="([a-z0-9]+)" selected', page, re.S
        )
        assert chosen
        data[f"tone_{key}"] = chosen[1]
    response = await phone.post("/wall/frames/columns", data={**data, **form})
    assert response.status_code == 303 and response.headers["location"] == "/wall/frames#columns"
    shown = await phone.get("/wall/frames")
    flash = re.search(r'<p class="flash" role="status">(.*?)</p>', shown.text, re.S)
    return html.unescape(flash[1]).strip() if flash else ""


async def test_with_nothing_chosen_the_wall_is_as_it_was(wall: Scenario) -> None:
    erin, husband = keys(wall)
    page = await screen(wall)
    assert order_on(page) == [erin, "together", husband]
    assert [tone_of(page, k) for k in (erin, "together", husband)] == ["p0", "family", "p1"]
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Erin")
        frames = (await phone.get("/wall/frames")).text
    assert "People on the wall" in frames and "Put them back" not in frames
    assert re.findall(r'id="column-([a-z0-9]+)"', frames) == [erin, "together", husband]
    assert all(words in frames for words in TONES.values())


async def test_moving_a_column_changes_the_walls_order_and_keeps_colours(wall: Scenario) -> None:
    erin, husband = keys(wall)
    async with web_client(wall) as phone:
        csrf = await sign_in(wall, phone, "Erin")
        # Teal for Erin on the form, then Up for her husband: both kept.
        assert "Moved." in await post(
            wall, phone, csrf, move=f"{husband}:up", **{f"tone_{erin}": "p4"}
        )
        await post(wall, phone, csrf, move=f"{husband}:up")
        await post(wall, phone, csrf, move=f"{husband}:up")  # already first: stays
    page = await screen(wall)
    assert order_on(page) == [husband, erin, "together"]
    assert tone_of(page, erin) == "p4" and tone_of(page, husband) == "p1"


async def test_a_chosen_colour_follows_the_person_on_the_wall(wall: Scenario) -> None:
    erin, husband = keys(wall)
    async with web_client(wall) as phone:
        csrf = await sign_in(wall, phone, "Erin")
        said = await post(wall, phone, csrf, **{f"tone_{husband}": "p6", "tone_together": "p2"})
    assert said.startswith("Saved the colours.")
    page = await screen(wall)
    assert tone_of(page, husband) == "p6" and tone_of(page, "together") == "p2"
    view = WallView(wall.app.services)
    assert view.timeline_rows() == [
        (erin, "Erin", "p0"),
        (husband, "Husband", "p6"),
        ("family", "Family", "p2"),
    ]
    assert view.tone_of(wall.member("Husband")) == "p6"
    async with web_client(wall) as phone:
        await sign_in(wall, phone, "Erin")
        person = await phone.get(f"/wall/view/person/{wall.member('Husband').id}")
    assert 'class="tone-p6 sheet-person"' in person.text


async def test_put_them_back(wall: Scenario) -> None:
    erin, husband = keys(wall)
    async with web_client(wall) as phone:
        csrf = await sign_in(wall, phone, "Erin")
        await post(wall, phone, csrf, move=f"{erin}:down", **{f"tone_{erin}": "p5"})
        assert "Put them back" in (await phone.get("/wall/frames")).text
        said = await post(wall, phone, csrf, reset="1")
    assert said == "The wall's columns are back as they were."
    page = await screen(wall)
    assert order_on(page) == [erin, "together", husband] and tone_of(page, erin) == "p0"


async def test_an_unknown_colour_or_column_changes_nothing(wall: Scenario) -> None:
    erin, husband = keys(wall)
    async with web_client(wall) as phone:
        csrf = await sign_in(wall, phone, "Erin")
        said = await post(wall, phone, csrf, **{f"tone_{erin}": "#ff0000"})
        assert said == "That isn't one of the wall's colours. Nothing changed."
        said = await post(wall, phone, csrf, order=f"{erin},together,{husband},m999")
        assert "Nothing changed" in said
        said = await post(wall, phone, csrf, order=f"{erin},{husband}")
        assert "Nothing changed" in said
    assert WallColumns(wall.app.services.store.db).chosen() == {}


async def test_only_admins_choose(wall: Scenario) -> None:
    erin, husband = keys(wall)
    async with web_client(wall) as phone:
        csrf = await sign_in(wall, phone, "Husband")
        response = await phone.post(
            "/wall/frames/columns",
            data={"csrf": csrf, "order": f"{husband},{erin},together", "move": f"{husband}:up"},
        )
    assert response.status_code == 403
    assert WallColumns(wall.app.services.store.db).chosen() == {}


def test_a_person_added_after_a_choice_goes_last_in_their_own_colour(wall: Scenario) -> None:
    erin, husband = wall.member("Erin"), wall.member("Husband")
    columns = WallColumns(wall.app.services.store.db)
    order = [f"m{husband.id}", "together", f"m{erin.id}"]
    columns.save(erin, [erin, husband], order, {f"m{erin.id}": "p3"})
    gran = replace(husband, id=husband.id + 100, name="Gran")
    laid = columns.layout([erin, husband, gran])
    assert [p.key for p in laid] == [*order, f"m{gran.id}"]
    assert [p.tone for p in laid] == ["p1", "family", "p3", "p2"]  # Gran's default is third
    # And a person who's gone is left out.
    assert [p.key for p in columns.layout([erin])] == ["together", f"m{erin.id}"]


def test_the_default_layout_puts_together_in_the_middle(wall: Scenario) -> None:
    erin = wall.member("Erin")
    assert [p.key for p in default_layout([erin])] == [f"m{erin.id}", "together"]
    assert [p.key for p in default_layout([])] == ["together"]
