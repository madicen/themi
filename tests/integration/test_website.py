"""The management website, driven over ASGI against the full app (fake Telegram, frozen clock)."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.fixtures.web import csrf_of, sign_in, web_client
from tests.scenarios.harness import Scenario
from themi import clock
from themi.accounts import Role
from themi.autonomy import ExecutionContext
from themi.core.calendar_view import CalendarPreferences
from themi.web.auth import COOKIE_NAME, WebAuth
from themi_home.chore_chart import ChartPreferences

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


@pytest.mark.usefixtures("fake_cozyla", "fake_gmail", "fake_gcal")  # CR7a/b1: their rows
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
        "chart_limit": "1",
        "calendar_twins": "guess",
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
    chart = scenario.app.store.preferences(erin.id, ChartPreferences)  # CR7a
    assert chart.chart_limit == 1 and not chart.chart_counts_shared  # left unticked
    assert (
        scenario.app.store.preferences(erin.id, CalendarPreferences).calendar_twins == "guess"
    )  # F34e
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


async def test_busy_times_can_be_added_and_removed(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    from datetime import time

    from themi.accounts import BusyTime

    csrf = await sign_in(scenario, site, "Erin")
    form = {"csrf": csrf, "start": "09:00", "end": "17:00"}
    form |= {f"day_{d}": "on" for d in range(5)}
    response = await site.post("/settings/busy", data=form)
    assert response.status_code == 303 and response.headers["location"] == "/settings"
    erin = scenario.app.store.get_member(scenario.member("Erin").id)
    assert erin.busy_times == (BusyTime((0, 1, 2, 3, 4), time(9), time(17)),)
    assert "Mon-Fri 09:00-17:00" in (await site.get("/settings")).text

    bad = await site.post("/settings/busy", data={"csrf": csrf, "start": "17:00", "end": "09:00"})
    assert bad.status_code == 400 and "at least one day" in bad.text

    removed = await site.post("/settings/busy/0/remove", data={"csrf": csrf})
    assert removed.status_code == 303
    assert scenario.app.store.get_member(erin.id).busy_times == ()
    missing = await site.post("/settings/busy/5/remove", data={"csrf": csrf})
    assert missing.status_code == 303  # already gone: nothing to do


# ----- the shell (W1) -------------------------------------------------------------


async def test_the_bottom_bar_marks_the_page_youre_on(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Husband")
    for path, current in (("/", "/"), ("/tasks", "/tasks"), ("/lists", "/lists"), ("/ai", "/more")):
        page = (await site.get(path)).text
        assert f'<a href="{current}" aria-current="page">' in page
        assert page.count('aria-current="page"') == 1
    home = (await site.get("/")).text
    assert "Sign out" in home and 'aria-label="Signed in as Husband"' in home


async def test_the_more_page_shows_admin_pages_only_to_admins(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Husband")
    member = (await site.get("/more")).text
    assert 'href="/settings"' in member and 'href="/tiers"' in member
    for admin_only in ('href="/family"', 'href="/dev"', 'href="/accounts#household"'):
        assert admin_only not in member
    async with web_client(scenario) as admin_site:
        await sign_in(scenario, admin_site, "Erin")
        admin = (await admin_site.get("/more")).text
        for admin_only in ('href="/family"', 'href="/dev"', 'href="/accounts#household"'):
            assert admin_only in admin


async def test_the_family_keeps_its_words_and_its_bar(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """A new Themi says "People" and puts Modules on an admin's bar; the family's doesn't."""
    await sign_in(scenario, site, "Erin")
    home = (await site.get("/")).text
    more = (await site.get("/more")).text
    bar = home[home.index('<nav class="tabs"') : home.index("</nav>")]
    assert 'href="/modules"' not in bar and 'href="/tasks"' in bar
    assert "<h2>Household</h2>" in more and ">Family</span>" in more
    assert "<h1>Family</h1>" in (await site.get("/family")).text


async def test_every_page_renders_in_the_new_shell(scenario: Scenario) -> None:
    pages = (
        "/",
        "/tasks",
        "/lists",
        "/more",
        "/settings",
        "/week",
        "/ai",
        "/accounts",
        "/knowledge",
        "/tiers",
        "/spending",
        "/maintenance",
        "/safeway",
    )  # /email/noise is the gmail module's (CR4): test_noise_digest renders it with Gmail
    for name, extra in (("Husband", ()), ("Erin", ("/family", "/dev"))):
        async with web_client(scenario) as client:
            await sign_in(scenario, client, name)
            for path in (*pages, *extra):
                response = await client.get(path)
                assert response.status_code == 200, path
                assert 'class="tabs"' in response.text, path
            assert (await client.get("/email/noise")).status_code == 404  # no Gmail here


def test_a_row_opens_on_tap_and_shows_its_chips() -> None:
    from jinja2 import Environment, FileSystemLoader

    from themi.web.kit import HERE

    env = Environment(loader=FileSystemLoader(str(HERE / "templates")), autoescape=True)
    template = env.from_string(
        '{% from "_row.html" import row %}'
        '{% call(part) row(title, meta="Due Thu", chips=[("Overdue", "warn"), "Weekly"],'
        " open=open) %}"
        '{% if part == "actions" %}<button>Done</button>{% else %}<p>Panel</p>{% endif %}'
        "{% endcall %}"
    )
    closed = template.render(title="Bins <out>", open=False)
    assert "<details>" in closed and "Bins &lt;out&gt;" in closed
    assert '<span class="chip warn">Overdue</span>' in closed
    assert '<span class="chip">Weekly</span>' in closed
    assert 'class="row-item has-actions"' in closed and "<button>Done</button>" in closed
    assert "<details open>" in template.render(title="Bins", open=True)


# ----- My settings in sections (W4) ---------------------------------------------------


async def test_each_settings_section_says_what_its_set_to(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    form = {
        "csrf": csrf,
        "quiet_start": "22:00",
        "quiet_end": "07:30",
        "daily_limit": "4",
        "phrasing": "gentle",
        "pda_enabled": "on",
        "pda_strength": "3",
        "morning_summary": "",
        "track_text_notes": "on",
        "track_reactions": "on",
    }
    await site.post("/settings", data=form)
    page = (await site.get("/settings")).text
    assert '<span class="row-meta">10 pm\u20137:30 am</span>' in page  # an en dash
    assert "At most 4 a day" in page
    assert "Gentle: indirect and low-key</span>" in page
    assert '<span class="row-meta">On, strict</span>' in page
    assert '<span class="row-title">Good-morning message</span>' in page and ">Off</span>" in page
    assert "2 of 5 on" in page

    await site.post("/settings", data={**form, "morning_summary": "07:15", "phrasing": "plain"})
    page = (await site.get("/settings")).text
    assert "Each morning at 7:15 am" in page and "Plain: say it straight</span>" in page


@pytest.mark.usefixtures("fake_cozyla", "fake_gmail", "fake_gcal")  # CR7a/b1: their rows
async def test_one_save_bar_saves_every_section(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    form = page[page.index('<form method="post" action="/settings"') :]
    form = form[: form.index("</form>")]
    for field in ("quiet_start", "daily_limit", "chart_limit", "noise_emails", "phrasing",
                  "pda_strength", "track_text_notes"):  # fmt: skip
        assert f'name="{field}"' in form, field
    assert '<div class="savebar">' in form and form.count("<button") == 1


async def test_a_changed_stylesheet_is_never_served_from_an_old_cache(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """Michael's phone kept the old themi.css after the redesign: no Cache-Control, so
    Safari guessed it was fresh. The URLs carry a fingerprint of the file, and static files
    are checked with the server before a cached copy is used."""
    import hashlib

    from themi.web.kit import HERE

    await sign_in(scenario, site, "Erin")
    page = (await site.get("/")).text
    for name in ("themi.css", "htmx.min.js"):
        digest = hashlib.sha256((HERE / "static" / name).read_bytes()).hexdigest()[:12]
        assert f"/static/{name}?v={digest}" in page, name
        response = await site.get(f"/static/{name}?v={digest}")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"


# ----- choosing the bar's pages (F28c, idea #144) -----------------------------------


def bar(page: str) -> list[str]:
    """The menu bar's links, in order."""
    nav = page[page.index('<nav class="tabs"') :]
    return re.findall(r'<a href="([^"]+)"', nav[: nav.index("</nav>")])


async def bar_change(site: httpx.AsyncClient, action: str, href: str = "") -> httpx.Response:
    csrf = csrf_of((await site.get("/more")).text)
    return await site.post("/more/bar", data={"csrf": csrf, "action": action, "href": href})


async def test_a_pinned_page_is_on_that_persons_bar_only(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Husband")
    assert bar((await site.get("/")).text) == ["/", "/tasks", "/lists", "/more"]  # the default

    pinned = await bar_change(site, "pin", "/spending")
    assert pinned.status_code == 303
    spending = (await site.get("/spending")).text
    assert bar(spending) == ["/", "/tasks", "/lists", "/spending", "/more"]
    assert '<a href="/spending" aria-current="page">' in spending
    assert spending.count('aria-current="page"') == 1
    assert scenario.app.store.get_member(scenario.member("Husband").id).menu_bar == (
        "/",
        "/tasks",
        "/lists",
        "/spending",
    )
    async with web_client(scenario) as erins:
        await sign_in(scenario, erins, "Erin")
        assert bar((await erins.get("/")).text) == ["/", "/tasks", "/lists", "/more"]


async def test_the_bar_holds_four_pages_and_more(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Husband")
    await bar_change(site, "pin", "/spending")
    refused = await bar_change(site, "pin", "/tiers")
    assert refused.status_code == 303
    page = (await site.get(refused.headers["location"])).text
    assert "The bar holds four pages" in page
    assert bar(page) == ["/", "/tasks", "/lists", "/spending", "/more"]
    nowhere = await bar_change(site, "pin", "https://example.com")
    assert nowhere.status_code == 400
    assert len(scenario.app.store.get_member(scenario.member("Husband").id).menu_bar or ()) == 4


async def test_pages_move_come_off_and_go_back_to_the_usual(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Husband")
    await bar_change(site, "unpin", "/lists")
    more = (await site.get("/more")).text
    assert bar(more) == ["/", "/tasks", "/more"]
    assert 'href="/lists"' in more[more.index("</nav>") :]  # still reachable from More
    await bar_change(site, "pin", "/week")
    await bar_change(site, "up", "/week")
    assert bar((await site.get("/")).text) == ["/", "/week", "/tasks", "/more"]
    await bar_change(site, "down", "/")
    assert bar((await site.get("/")).text) == ["/week", "/", "/tasks", "/more"]
    await bar_change(site, "reset")
    assert bar((await site.get("/")).text) == ["/", "/tasks", "/lists", "/more"]
    assert scenario.app.store.get_member(scenario.member("Husband").id).menu_bar is None


async def test_an_admin_page_leaves_the_bar_when_the_role_does(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    await bar_change(site, "pin", "/family")
    assert "/family" in bar((await site.get("/")).text)
    store = scenario.app.store
    erin = store.get_member(scenario.member("Erin").id)
    store.set_role(erin, scenario.member("Husband").id, Role.ADMIN)
    store.set_role(erin, erin.id, Role.MEMBER)
    assert bar((await site.get("/")).text) == ["/", "/tasks", "/lists", "/more"]
    refused = await bar_change(site, "pin", "/dev")
    assert refused.status_code == 400
