"""The management website, driven over ASGI against the full app (fake Telegram, frozen clock)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.autonomy import ExecutionContext
from themi.web.auth import COOKIE_NAME, WebAuth

# ----- signing in ---------------------------------------------------------------


async def test_pages_need_a_session(site: httpx.AsyncClient) -> None:
    for path in ("/", "/settings"):
        response = await site.get(path)
        assert response.status_code == 303 and response.headers["location"] == "/signed-out"
    signed_out = await site.get("/signed-out")
    assert "Sending /site to Themi" in signed_out.text


async def test_opening_a_link_doesnt_use_it_up(scenario: Scenario, site: httpx.AsyncClient) -> None:
    """Telegram's link preview fetches the URL; that must not sign anyone in or burn the link."""
    token = WebAuth(scenario.app.store).create_link_token(scenario.member("Erin"))
    preview = await site.get(f"/login/{token}")
    assert preview.status_code == 200 and "Continue" in preview.text
    assert COOKIE_NAME not in preview.cookies
    signed_in = await site.post(f"/login/{token}")
    assert signed_in.status_code == 303
    home = await site.get("/")
    assert home.status_code == 200 and "Hi Erin" in home.text


async def test_session_cookie_flags(scenario: Scenario) -> None:
    for secure in (False, True):
        async with web_client(scenario, secure=secure) as client:
            token = WebAuth(scenario.app.store).create_link_token(scenario.member("Erin"))
            response = await client.post(f"/login/{token}")
            cookie = response.headers["set-cookie"].lower()
            assert "httponly" in cookie and "samesite=lax" in cookie
            assert ("secure" in cookie) is secure


async def test_links_work_once(scenario: Scenario, site: httpx.AsyncClient) -> None:
    token = WebAuth(scenario.app.store).create_link_token(scenario.member("Erin"))
    assert (await site.post(f"/login/{token}")).status_code == 303
    again = await site.post(f"/login/{token}")
    assert again.status_code == 410 and "expired" in again.text
    assert (await site.get(f"/login/{token}")).status_code == 410


async def test_links_expire_after_ten_minutes(scenario: Scenario, site: httpx.AsyncClient) -> None:
    token = WebAuth(scenario.app.store).create_link_token(scenario.member("Erin"))
    clock.advance(timedelta(minutes=10))
    assert (await site.post(f"/login/{token}")).status_code == 410
    fresh = WebAuth(scenario.app.store).create_link_token(scenario.member("Erin"))
    clock.advance(timedelta(minutes=9, seconds=59))
    assert (await site.post(f"/login/{fresh}")).status_code == 303


async def test_unknown_links_are_refused(site: httpx.AsyncClient) -> None:
    assert (await site.post("/login/not-a-real-token")).status_code == 410


async def test_signing_out_ends_the_session(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    response = await site.post("/logout", data={"csrf": csrf})
    assert response.status_code == 303
    assert (await site.get("/")).status_code == 303


# ----- CSRF ---------------------------------------------------------------------


async def test_posts_without_the_csrf_token_are_refused(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    form = {"quiet_start": "20:00", "quiet_end": "07:00", "daily_limit": "1", "pda_strength": "2"}
    assert (await site.post("/settings", data=form)).status_code == 403
    assert (await site.post("/settings", data={**form, "csrf": "forged"})).status_code == 403
    assert scenario.app.store.get_member(scenario.member("Erin").id).daily_limit == 6


async def test_the_csrf_header_works_for_htmx(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    form = {"quiet_start": "21:30", "quiet_end": "08:00", "daily_limit": "4", "pda_strength": "2"}
    response = await site.post("/settings", data=form, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 303


# ----- settings -------------------------------------------------------------------


async def test_settings_are_saved(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    form = {
        "csrf": csrf,
        "quiet_start": "22:15",
        "quiet_end": "07:45",
        "daily_limit": "3",
        "pda_enabled": "on",
        "pda_strength": "3",
        "track_text_notes": "on",
        # message_timing and device_activity left unticked
    }
    response = await site.post("/settings", data=form)
    assert response.status_code == 303 and response.headers["location"] == "/settings"
    erin = scenario.app.store.get_member(scenario.member("Erin").id)
    assert (erin.quiet_start.strftime("%H:%M"), erin.quiet_end.strftime("%H:%M")) == (
        "22:15",
        "07:45",
    )
    assert (erin.daily_limit, erin.pda_enabled, erin.pda_strength) == (3, True, 3)
    assert erin.tracks("text_notes") and not erin.tracks("message_timing")
    page = await site.get("/settings")
    assert "Saved." in page.text and 'value="22:15"' in page.text
    assert "Saved." not in (await site.get("/settings")).text  # the message shows once


async def test_bad_values_are_explained_and_change_nothing(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    form = {
        "csrf": csrf,
        "quiet_start": "21:30",
        "quiet_end": "08:00",
        "daily_limit": "99",
        "pda_strength": "2",
        "pda_enabled": "on",
    }
    response = await site.post("/settings", data=form)
    assert response.status_code == 400 and "between 0 and 50" in response.text
    assert scenario.app.store.get_member(scenario.member("Erin").id).daily_limit == 6


async def test_members_only_ever_touch_their_own_settings(scenario: Scenario) -> None:
    async with web_client(scenario) as erins, web_client(scenario) as his:
        erin_csrf = await sign_in(scenario, erins, "Erin")
        await sign_in(scenario, his, "Husband")
        husband = scenario.member("Husband")
        form = {
            "csrf": erin_csrf,
            "member_id": str(husband.id),
            "quiet_start": "20:00",
            "quiet_end": "06:00",
            "daily_limit": "1",
            "pda_strength": "0",
        }
        await erins.post("/settings", data=form)
        assert scenario.app.store.get_member(husband.id).daily_limit == husband.daily_limit
        assert scenario.app.store.get_member(scenario.member("Erin").id).daily_limit == 1
        his_page = await his.get("/settings")
        assert 'value="23:00"' in his_page.text and 'value="20:00"' not in his_page.text


# ----- dashboard and approvals ----------------------------------------------------


@pytest.fixture
def archived(scenario: Scenario) -> list[dict]:
    done: list[dict] = []

    @scenario.app.services.autonomy.executors.register("gmail.archive")
    async def archive(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        done.append(payload)
        return "Archived 3 promos."

    return done


async def stage(scenario: Scenario, name: str = "Erin") -> int:
    outcome = await scenario.app.services.autonomy.stage(
        "email_archive_noise",
        scenario.member(name),
        "Archive 3 promo emails",
        {"n": 3},
        "gmail.archive",
    )
    return outcome.action.id


async def test_approving_from_the_dashboard_runs_it_and_tidies_telegram(
    scenario: Scenario, site: httpx.AsyncClient, archived: list[dict]
) -> None:
    action_id = await stage(scenario)
    csrf = await sign_in(scenario, site, "Erin")
    home = await site.get("/")
    assert "Archive 3 promo emails" in home.text and "Go ahead" in home.text
    response = await site.post(f"/actions/{action_id}/approve", data={"csrf": csrf})
    assert response.status_code == 303
    assert archived == [{"n": 3}]
    after = await site.get("/")
    assert "Archived 3 promos." in after.text  # the flash
    assert "Done: Archive 3 promo emails" in after.text  # recent activity
    assert scenario.edits("Erin")[-1]["text"].endswith("Done. Archived 3 promos.")


async def test_htmx_gets_just_the_updated_card(
    scenario: Scenario, site: httpx.AsyncClient, archived: list[dict]
) -> None:
    action_id = await stage(scenario)
    csrf = await sign_in(scenario, site, "Erin")
    response = await site.post(
        f"/actions/{action_id}/snooze", headers={"HX-Request": "true", "X-CSRF-Token": csrf}
    )
    assert response.status_code == 200
    assert response.text.startswith(f'<article class="card action" id="action-{action_id}">')
    assert "<html" not in response.text and "bring it back later" in response.text


async def test_someone_elses_personal_action_cant_be_approved(
    scenario: Scenario, site: httpx.AsyncClient, archived: list[dict]
) -> None:
    action_id = await stage(scenario, "Husband")
    csrf = await sign_in(scenario, site, "Erin")
    assert "Archive 3 promo emails" not in (await site.get("/")).text
    await site.post(f"/actions/{action_id}/approve", data={"csrf": csrf})
    assert archived == []
    assert "yours to answer" in (await site.get("/")).text


async def test_admins_see_escalations(scenario: Scenario, site: httpx.AsyncClient) -> None:
    scenario.app.services.autonomy.escalate("email_mark_read", "the PG&E confirmation is late")
    await sign_in(scenario, site, "Erin")
    assert "the PG&amp;E confirmation is late" in (await site.get("/")).text


# ----- the page itself ------------------------------------------------------------


async def test_security_headers_and_no_caching(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Erin")
    response = await site.get("/")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


async def test_vendored_assets_are_served(site: httpx.AsyncClient) -> None:
    htmx = await site.get("/static/htmx.min.js")
    assert htmx.status_code == 200 and htmx.text.startswith("var htmx=")
    css = await site.get("/static/themi.css")
    assert css.status_code == 200 and "prefers-color-scheme: dark" in css.text
