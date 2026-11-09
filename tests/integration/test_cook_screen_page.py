"""CK1: the cook screen on /session: who may see and tap it, an old `seq`, the kitchen
view's redirect, and a tap on the page editing the chat's card. The clock starts Wednesday
21 October 2026, 9 am."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.cookbook import load
from tests.fixtures.web import csrf_of, sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, RANCH, lines
from themi.core import keys
from themi_home.cooking import Cooking, Session


@pytest.fixture
def cooking(scenario: Scenario) -> Cooking:
    load(scenario.app.services)
    found = scenario.app.services.maybe(keys.cooking)
    assert found is not None
    return found


async def start(
    scenario: Scenario,
    cooking: Cooking,
    name: str = "Erin",
    *,
    recipe: str = "Silken Tofu Ranch Dressing",
    in_group: bool = False,
) -> Session:
    scenario.primary.queue_structured(lines(ALFREDO if recipe == "Alfredo Sauce" else RANCH))
    found = next(r for r in cooking.recipes.all() if r.name == recipe)
    return await cooking.start(scenario.member(name), found, in_group=in_group)


async def act(site: httpx.AsyncClient, session_id: int, csrf: str, action: str, seq: int,
              **extra: str) -> httpx.Response:  # fmt: skip
    return await site.post(
        f"/session/cook/{session_id}/act",
        headers={"X-Requested-With": "fetch"},
        data={"csrf": csrf, "action": action, "seq": str(seq), **extra},
    )


async def test_the_page_is_the_cook_screen(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    await sign_in(scenario, site, "Erin")
    await start(scenario, cooking, recipe="Alfredo Sauce")
    page = await site.get("/session")
    assert page.status_code == 200
    assert 'class="session-page cook-page"' in page.text and "home/cook.js" in page.text
    assert "Before anything else" in page.text and "soak the cashews (10 min)" in page.text
    assert "frame-ancestors https://web.telegram.org" in page.headers["content-security-policy"]
    state = (await site.get("/session/state")).json()
    assert (state["kind"], state["phase"]) == ("cooking", "ready")
    view = await site.get("/session/cook/view")
    assert f'data-drawn="{state["drawn"]}"' in view.text


async def test_a_body_double_session_comes_first(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    await sign_in(scenario, site, "Erin")
    await start(scenario, cooking)
    body_double = scenario.app.services.maybe(keys.body_double)
    assert body_double is not None
    await body_double.start(scenario.member("Erin"), mode="silent", label="the dishes")
    state = (await site.get("/session/state")).json()
    assert state.get("kind") != "cooking" and state["label"] == "the dishes"  # the plan's order
    assert "cook-page" not in (await site.get("/session")).text


async def test_a_tap_moves_the_session_and_edits_the_chat_card(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    session = await start(scenario, cooking)
    seq = (await site.get("/session/state")).json()["seq"]
    scenario.primary.queue_structured({"jobs": []})
    state = (await act(site, session.id, csrf, "next", seq)).json()
    assert state["phase"] == "cook" and state["seq"] > seq
    assert scenario.edits("Erin")[-1]["text"].startswith(
        "Silken Tofu Ranch Dressing: step 1 of 1"
    )  # the chat's card moved too
    assert "All done" in [b["label"] for b in state["buttons"]]
    plain = await site.post(
        f"/session/cook/{session.id}/act",
        data={"csrf": csrf, "action": "back", "seq": str(state["seq"])},
    )
    assert plain.status_code == 303 and plain.headers["location"] == "/session"


async def test_an_old_seq_does_nothing(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    session = await start(scenario, cooking)
    seq = (await site.get("/session/state")).json()["seq"]
    state = (await act(site, session.id, csrf, "stop", seq - 1)).json()
    assert state["active"] is True and state["phase"] == "gather"
    assert (await act(site, session.id, "not-the-csrf", "stop", seq)).status_code in (400, 403)
    assert cooking.current(scenario.member("Erin")) is not None


async def test_someone_elses_session_is_404(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    session = await start(scenario, cooking, "Husband")
    csrf = await sign_in(scenario, site, "Erin")
    assert "No session going on" in (await site.get("/session")).text
    response = await act(site, session.id, csrf, "stop", session.seq)
    assert response.status_code == 404
    assert cooking.current(scenario.member("Husband")) is not None


async def test_either_partner_on_a_group_session(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    session = await start(scenario, cooking, "Erin", in_group=True)
    csrf = await sign_in(scenario, site, "Husband")
    state = (await site.get("/session/state")).json()
    assert state["id"] == session.id
    state = (await act(site, session.id, csrf, "tick", state["seq"], list="gather", n="1")).json()
    assert state["gather"][1]["ticked"] is True


async def test_the_kitchen_view_redirects_to_the_session(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    for path in ("/recipes/kitchen", "/recipes/kitchen/state"):
        response = await site.get(path)
        assert (response.status_code, response.headers["location"]) == (303, "/session")
    moved = await site.post("/recipes/kitchen/1/next", data={"csrf": csrf})
    assert (moved.status_code, moved.headers["location"]) == (303, "/session")


async def test_open_in_kitchen_view_on_the_chat_card(scenario: Scenario, cooking: Cooking) -> None:
    scenario.app.services.site_url = "https://themi.example.ts.net"
    await start(scenario, cooking)
    keyboard = scenario.telegram.last_keyboard(scenario.member("Erin").telegram_user_id or 0)
    opened = [b for b in keyboard if b["text"] == "Open in kitchen view"]
    assert opened and opened[0]["web_app"] == {"url": "https://themi.example.ts.net/session"}


async def test_the_page_form_posts_carry_the_seq(
    scenario: Scenario, site: httpx.AsyncClient, cooking: Cooking
) -> None:
    await sign_in(scenario, site, "Erin")
    session = await start(scenario, cooking)
    page = (await site.get("/session")).text
    seq = (await site.get("/session/state")).json()["seq"]
    assert f'action="/session/cook/{session.id}/act"' in page
    assert f'name="seq" value="{seq}"' in page and csrf_of(page)
