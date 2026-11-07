"""Family, trust tiers, rules and memory, and My AI pages."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.web import csrf_of, sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.ai.settings import AITask
from themi.autonomy import Tier
from themi.core import keys
from themi.core.pantry import PantrySettings
from themi.core.spending import SpendingSettings
from themi.storage.secrets import Secret

GEMINI_KEY = "AIzaVeryDistinctiveTestKey000000000000000"


# ----- household connections on Accounts (W3) --------------------------------------


@pytest.mark.usefixtures("fake_thinq", "fake_roborock", "fake_home_connect")
async def test_household_connections_are_on_accounts_for_admins_only(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Husband")
    member = (await site.get("/accounts")).text
    assert "My Google accounts" in member
    assert 'id="household"' not in member and "/family/thinq/link" not in member
    async with web_client(scenario) as admin_site:
        await sign_in(scenario, admin_site, "Erin")
        accounts = (await admin_site.get("/accounts")).text
        assert 'id="household"' in accounts
        for row in ("thinq", "roborock", "home-connect"):
            assert f'id="{row}"' in accounts
        family = (await admin_site.get("/family")).text
        for gone in ("LG ThinQ", "Roborock", "Home Connect", "/family/calendar"):
            assert gone not in family
        assert 'href="/accounts#household"' in family


@pytest.mark.usefixtures("fake_thinq", "fake_roborock")
async def test_a_connection_row_opens_when_asked(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    closed = (await site.get("/accounts")).text
    opened = (await site.get("/accounts?open=thinq")).text
    assert '<div class="row-item" id="thinq">\n  <details open>' in opened
    assert '<div class="row-item" id="thinq">\n  <details>' in closed
    assert '<div class="row-item" id="roborock">\n  <details>' in opened


# ----- family (admins only) ----------------------------------------------------


async def test_the_family_page_is_for_admins(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    page = await site.get("/family")
    assert page.status_code == 403 and "Admins only" in page.text
    assert "/family" not in (await site.get("/")).text  # no nav link either
    response = await site.post(
        "/family", data={"csrf": csrf, "name": "Mine now", "timezone": "UTC", "budget": "0"}
    )
    assert response.status_code == 403
    assert scenario.app.store.get_family().name == "Household"  # type: ignore[union-attr]


async def test_admins_edit_family_settings(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    response = await site.post(
        "/family",
        data={
            "csrf": csrf,
            "name": "The Household",
            "timezone": "America/Denver",
            "budget": "$250",
            "staples": "eggs\n\noat milk\n rice ",
        },
    )
    assert response.status_code == 303
    family = scenario.app.store.get_family()
    assert family is not None
    assert (family.name, family.timezone) == ("The Household", "America/Denver")
    store = scenario.app.store  # CR7c: the modules' own
    assert store.household(SpendingSettings).takeout_budget_cents == 250_00
    assert store.household(PantrySettings).staples == ("eggs", "oat milk", "rice")
    bad = await site.post(
        "/family", data={"csrf": csrf, "name": "x", "timezone": "Moon/Base", "budget": "1"}
    )
    assert bad.status_code == 400 and "isn&#39;t a timezone" in bad.text


async def test_adding_people_and_invites(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/family/members", data={"csrf": csrf, "name": "Grandma", "role": "member"})
    page = (await site.get("/family")).text
    assert "Invite code for Grandma:" in page and "/start " in page
    grandma = scenario.app.store.member_by_name("Grandma")
    assert grandma is not None and not grandma.is_admin
    await site.post(f"/family/members/{grandma.id}/invite", data={"csrf": csrf})
    assert "Invite code for Grandma:" in (await site.get("/family")).text
    await site.post(f"/family/members/{grandma.id}/role", data={"csrf": csrf, "role": "admin"})
    assert scenario.app.store.get_member(grandma.id).is_admin


async def test_the_last_admin_is_protected(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    erin = scenario.member("Erin")
    await site.post(f"/family/members/{erin.id}/role", data={"csrf": csrf, "role": "member"})
    assert "at least one admin" in (await site.get("/family")).text
    assert scenario.app.store.get_member(erin.id).is_admin


async def test_removing_someone_needs_their_name(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    husband = scenario.member("Husband")
    await site.post(
        f"/family/members/{husband.id}/remove", data={"csrf": csrf, "confirm_name": "x"}
    )
    assert scenario.app.store.member_by_name("Husband") is not None
    await site.post(
        f"/family/members/{husband.id}/remove", data={"csrf": csrf, "confirm_name": "husband"}
    )
    assert scenario.app.store.member_by_name("Husband") is None


# ----- trust tiers --------------------------------------------------------------


async def test_members_can_see_tiers_but_only_admins_change_shared_ones(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Husband")
    page = (await site.get("/tiers")).text
    card = page[page.index("Add items to the grocery list") :][:500]
    assert "Asks first." in card and "Make automatic" not in card
    await site.post("/tiers/grocery_list_add/automatic", data={"csrf": csrf})
    assert scenario.app.services.autonomy.category("grocery_list_add").tier is Tier.SUPERVISED
    assert "takes an admin" in (await site.get("/tiers")).text


async def test_making_a_category_automatic_locks_a_rule(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/tiers/grocery_list_add/automatic", data={"csrf": csrf})
    autonomy, rulebook = scenario.app.services.autonomy, scenario.app.rulebook
    assert autonomy.category("grocery_list_add").tier is Tier.AUTOMATIC
    (rule,) = rulebook.locked()
    assert rule.summary == "Automatic: Add items to the grocery list"
    assert rule.text == "Themi may add items to the grocery list without asking first."
    assert rule.scope == "household"
    assert "Ask first again" in (await site.get("/tiers")).text

    await site.post("/tiers/grocery_list_add/supervised", data={"csrf": csrf})
    assert autonomy.category("grocery_list_add").tier is Tier.SUPERVISED
    assert rulebook.locked() == []


async def test_a_personal_category_is_switched_per_person(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    # Bug #58 / idea #62: Erin's switch archives only her own noise.
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/tiers/email_archive_noise/automatic", data={"csrf": csrf})
    autonomy, rulebook = scenario.app.services.autonomy, scenario.app.rulebook
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    assert autonomy.is_automatic("email_archive_noise", erin)
    assert not autonomy.is_automatic("email_archive_noise", husband)
    (rule,) = rulebook.locked()
    assert rule.summary == "Automatic for Erin: Archive noise emails"
    assert rule.scope == "personal"

    csrf = await sign_in(scenario, site, "Husband")  # not an admin, and still his to switch
    page = (await site.get("/tiers")).text
    card = page[page.index("Archive noise emails") :][:600]
    assert "For you: asks first." in card and "Automatic for Erin." in card
    assert "Make automatic for me" in card
    await site.post("/tiers/email_archive_noise/automatic", data={"csrf": csrf})
    assert autonomy.granted_to("email_archive_noise") == [erin.id, husband.id]
    await site.post("/tiers/email_archive_noise/supervised", data={"csrf": csrf})
    assert autonomy.granted_to("email_archive_noise") == [erin.id]
    await site.post("/tiers/grocery_list_add/automatic", data={"csrf": csrf})
    assert autonomy.category("grocery_list_add").tier is Tier.SUPERVISED  # shared: admins


async def test_capped_categories_have_no_switch_and_refuse_a_forged_one(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/tiers")).text
    card = page[page.index("Send an email reply") : page.index("Send an email reply") + 400]
    assert "can't become automatic" in card and "Make automatic" not in card
    await site.post("/tiers/email_reply/automatic", data={"csrf": csrf})
    assert scenario.app.services.autonomy.category("email_reply").tier is Tier.SUPERVISED
    assert "always needs a yes" in (await site.get("/tiers")).text


async def test_escalated_categories_can_be_resumed(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/tiers/email_mark_read/automatic", data={"csrf": csrf})
    scenario.app.services.autonomy.escalate("email_mark_read", "a bill confirmation is late")
    page = (await site.get("/tiers")).text
    assert "a bill confirmation is late" in page and "Resume automatic" in page
    await site.post("/tiers/email_mark_read/resume", data={"csrf": csrf})
    assert not scenario.app.services.autonomy.category("email_mark_read").escalated


# ----- rules and memory -----------------------------------------------------------


async def test_facts_show_household_and_your_own_only(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    memory = scenario.app.services.maybe(keys.memory)
    assert memory is not None
    memory.remember(scenario.member("Erin"), "bins", "Bins go out Wednesday mornings.")
    his = memory.remember(
        scenario.member("Husband"), "coffee", "He takes his coffee black.", scope="member"
    )
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/knowledge")).text
    assert "Bins go out Wednesday mornings." in page and "coffee black" not in page
    await site.post(f"/facts/{his.id}/edit", data={"csrf": csrf, "fact": "Tea now."})
    await site.post(f"/facts/{his.id}/delete", data={"csrf": csrf})
    assert memory.get(his.id).fact == "He takes his coffee black."


async def test_pinning_editing_and_forgetting_facts(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    memory = scenario.app.services.maybe(keys.memory)
    assert memory is not None
    fact = memory.remember(scenario.member("Erin"), "vet", "Vet on Mondays.")
    csrf = await sign_in(scenario, site, "Husband")  # household facts: anyone may edit
    await site.post(f"/facts/{fact.id}/pin", data={"csrf": csrf})
    assert memory.get(fact.id).pinned
    await site.post(f"/facts/{fact.id}/edit", data={"csrf": csrf, "fact": "Vet on Tuesdays."})
    assert memory.get(fact.id).fact == "Vet on Tuesdays."
    await site.post(f"/facts/{fact.id}/delete", data={"csrf": csrf})
    assert memory.visible(scenario.member("Erin")) == []


async def test_drafts_and_rules_from_the_page(scenario: Scenario, site: httpx.AsyncClient) -> None:
    rulebook = scenario.app.rulebook
    draft = await rulebook.propose(scenario.member("Erin"), "Bins reminder", "Mention the bins.")
    csrf = await sign_in(scenario, site, "Erin")
    assert "Bins reminder" in (await site.get("/knowledge")).text
    await site.post(f"/rules/{draft.id}/lock", data={"csrf": csrf})
    assert [r.id for r in rulebook.locked()] == [draft.id]
    await site.post(f"/rules/{draft.id}/retire", data={"csrf": csrf})
    assert rulebook.locked() == []


async def test_the_partner_cant_lock_your_draft(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    draft = await scenario.app.rulebook.propose(scenario.member("Erin"), "Bins", "Bins.")
    csrf = await sign_in(scenario, site, "Husband")
    await site.post(f"/rules/{draft.id}/lock", data={"csrf": csrf})
    assert scenario.app.rulebook.locked() == []


# ----- my AI ------------------------------------------------------------------------


async def test_keys_are_never_rendered_back(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post(
        "/ai/backends",
        data={
            "csrf": csrf,
            "label": "My Gemini",
            "kind": "gemini",
            "model": "",
            "api_key": GEMINI_KEY,
            "supports_tools": "on",
            "supports_structured": "on",
        },
    )
    page = (await site.get("/ai")).text
    assert "My Gemini" in page and "saved (leave blank to keep)" in page
    assert GEMINI_KEY not in page and GEMINI_KEY[:8] not in page
    raw = scenario.app.db.scalar("SELECT api_key FROM ai_backends WHERE label = 'My Gemini'")
    assert GEMINI_KEY.encode() not in raw


async def test_blank_key_keeps_it_and_remove_clears_it(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    ai = scenario.app.ai_settings
    erin = scenario.member("Erin")
    backend = ai.add_backend(erin, erin.id, "Claude", "anthropic", api_key=Secret("sk-ant-x"))
    csrf = await sign_in(scenario, site, "Erin")
    form = {
        "csrf": csrf,
        "label": "Claude",
        "model": "claude-opus-5-5",
        "api_key": "",
        "timeout": "60",
        "supports_tools": "on",
        "supports_structured": "on",
        "effort": "low",
    }
    await site.post(f"/ai/backends/{backend.id}", data=form)
    updated = ai.get_backend(backend.id)
    assert updated.has_key and (updated.model, updated.effort) == ("claude-opus-5-5", "low")
    await site.post(f"/ai/backends/{backend.id}", data={**form, "remove_key": "on"})
    assert not ai.get_backend(backend.id).has_key


async def test_you_cant_touch_someone_elses_backends(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    ai = scenario.app.ai_settings
    husband = scenario.member("Husband")
    his = ai.add_backend(husband, husband.id, "His Claude", "anthropic", api_key=Secret("his"))
    csrf = await sign_in(scenario, site, "Erin")  # an admin, and still not allowed
    assert "His Claude" not in (await site.get("/ai")).text
    await site.post(f"/ai/backends/{his.id}", data={"csrf": csrf, "label": "Mine", "timeout": "60"})
    await site.post(f"/ai/backends/{his.id}/remove", data={"csrf": csrf})
    assert ai.get_backend(his.id).label == "His Claude"
    erin = scenario.member("Erin")
    await site.post(
        f"/ai/chains/{AITask.CONVERSATION.value}", data={"csrf": csrf, "backend_0": str(his.id)}
    )
    assert his.id not in [e.backend_id for e in ai.chain(erin.id, AITask.CONVERSATION)]


async def test_saving_a_chain(scenario: Scenario, site: httpx.AsyncClient) -> None:
    ai = scenario.app.ai_settings
    erin = scenario.member("Erin")
    primary, fallback = ai.backends(erin.id)[:2]
    csrf = await sign_in(scenario, site, "Erin")
    await site.post(
        f"/ai/chains/{AITask.EMAIL_TRIAGE.value}",
        data={
            "csrf": csrf,
            "backend_0": str(fallback.id),
            "model_0": "big-model",
            "backend_1": str(primary.id),
            "backend_2": "",
        },
    )
    chain = ai.chain(erin.id, AITask.EMAIL_TRIAGE)
    assert [(e.backend_id, e.model) for e in chain] == [
        (fallback.id, "big-model"),
        (primary.id, None),
    ]


async def test_connection_test_reports_success_and_failure(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    scenario.primary.queue_text("OK")
    response = await site.post(
        f"/ai/test/{AITask.CONVERSATION.value}",
        headers={"HX-Request": "true", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200 and "Primary is connected (primary)" in response.text
    scenario.primary.fail(1, status=403)
    response = await site.post(f"/ai/test/{AITask.CONVERSATION.value}", data={"csrf": csrf})
    assert response.status_code == 303
    assert "Primary didn&#39;t answer" in (await site.get("/ai")).text


async def test_a_new_member_sees_the_free_tier_default(scenario: Scenario) -> None:
    scenario.clear_ai_settings(scenario.member("Husband"))
    async with web_client(scenario) as client:
        await sign_in(scenario, client, "Husband")
        page = (await client.get("/ai")).text
    assert "Gemini (free tier)" in page and "not set" in page
    assert "Google may use what's sent to improve its products" in page
    assert csrf_of(page)


# ----- reply times (P2a; admins only) ----------------------------------------------


async def test_reply_times_show_where_the_time_went(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    scenario.primary.take(16).queue_tool_call("list_open_items", {})
    scenario.primary.take(18).queue_text("Nothing open.")
    await scenario.say("Erin", "What's open?")
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/dev")).text
    assert "1 reply." in page and "still coming" in page
    assert "34.0 s · Erin" in page
    assert "Model: 16.0 s (Primary)" in page and "Tool list_open_items: 0.0 s" in page


async def test_reply_times_show_how_the_tool_groups_did(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    # P3: a reply where the words chose enough, and one where the model asked for more.
    scenario.primary.take(2).queue_text("Okay.")
    await scenario.say("Erin", "Make a packing list for the trip")
    scenario.primary.take(3).queue_tool_call("more_tools", {"groups": ["pantry"]})
    scenario.primary.take(4).queue_text("Done.")
    await scenario.say("Erin", "Hmm, what should we do about that")
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/dev")).text
    assert "1 of 2 replies needed more tools." in page
    assert "Replies that needed more: 7.0 s (median)." in page
    assert "Replies that didn't: 2.0 s (median)." in page
    assert "Added late: pantry (1)." in page
    lists = len(scenario.app.services.tools.specs({"lists"}))  # the same for both
    assert f"Tools sent at the start: {lists} (median)." in page
    assert "(core, lists), then pantry." in page  # the slowest, step by step


async def test_reply_times_count_the_calls_sent_twice(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    # P2b: a stuck call sent again, and one where the first still answered first.
    scenario.app.router.hedge_after = 5
    scenario.primary.take(30).queue_text("Tuesday.")
    await scenario.say("Erin", "When's the vet?")
    scenario.primary.take(7).take(9).queue_text("Wednesday.").queue_text("Thursday.")
    await scenario.say("Erin", "And the dentist?")
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/dev")).text
    assert "2 slow model calls were sent a second time; the second answered first 1 time." in page
    assert "sent again, the first answered" in page


async def test_reply_times_are_for_admins(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Husband")
    assert (await site.get("/dev")).status_code == 403
    assert (await site.get("/ai/timing")).status_code == 403
    assert "/dev" not in (await site.get("/")).text
    assert "/dev" not in (await site.get("/more")).text


async def test_reply_times_moved_to_the_development_page(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    # D3a: the old address still works, for bookmarks.
    await sign_in(scenario, site, "Erin")
    response = await site.get("/ai/timing")
    assert response.status_code == 303 and response.headers["location"] == "/dev"
    assert 'href="/dev"' in (await site.get("/more")).text  # W1: on the More page


# ----- rows with chips (W5) ---------------------------------------------------------


def row_of(page: str, row_id: str) -> str:
    start = page.index(f'id="{row_id}"')
    return page[start : page.index("</summary>", start)]


async def test_each_tier_says_its_state_on_the_row(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post("/tiers/grocery_list_add/automatic", data={"csrf": csrf})
    await site.post("/tiers/email_mark_read/automatic", data={"csrf": csrf})
    scenario.app.services.autonomy.escalate("email_mark_read", "a bill confirmation is late")
    page = (await site.get("/tiers")).text
    assert '<span class="chip good">Automatic</span>' in row_of(page, "tier-grocery_list_add")
    paused = row_of(page, "tier-email_mark_read")
    assert '<span class="chip warn">Paused</span>' in paused
    assert "Asking again because: a bill confirmation is late" in paused
    capped = row_of(page, "tier-email_reply")
    assert '<span class="chip">Always asks</span>' in capped and "Yours to switch" not in capped
    archive = row_of(page, "tier-email_archive_noise")
    assert '<span class="chip">Asks first</span>' in archive and "Yours to switch" in archive


async def test_each_ai_job_shows_its_chain(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/ai")).text
    labels = [b.label for b in scenario.app.ai_settings.backends(scenario.member("Erin").id)]
    chain = row_of(page, "job-conversation")
    assert "Conversation" in chain and " → ".join(labels[:2]) in chain


async def test_the_picture_switch_and_the_picture_cap(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """F34gb: an OpenAI-compatible backend can be marked as seeing pictures (Claude's form
    has no such box), and the cap on pictures sent in chat is theirs to set."""
    ai = scenario.app.ai_settings
    erin = scenario.member("Erin")
    local = ai.add_backend(erin, erin.id, "Laptop", "ollama", model="llava")
    claude = ai.add_backend(erin, erin.id, "Claude", "anthropic", api_key=Secret("sk-ant-x"))
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/ai")).text

    def form_of(backend_id: int) -> str:
        return page.split(f'id="backend-{backend_id}"')[1].split("</form>")[0]

    assert 'name="supports_images"' in form_of(local.id)
    assert 'name="supports_images"' not in form_of(claude.id)
    assert 'name="picture_daily_cap" min="0" max="500" value="100"' in page
    form = {"csrf": csrf, "label": "Laptop", "model": "llava", "timeout": "60"}
    await site.post(f"/ai/backends/{local.id}", data={**form, "supports_images": "on"})
    assert ai.get_backend(local.id).supports_images
    await site.post(f"/ai/backends/{local.id}", data=form)
    assert not ai.get_backend(local.id).supports_images

    await site.post("/ai/picture-cap", data={"csrf": csrf, "picture_daily_cap": "12"})
    cap = "SELECT picture_daily_cap FROM members WHERE id = ?"
    assert scenario.app.db.one(cap, (erin.id,))["picture_daily_cap"] == 12  # type: ignore[index]
    await site.post("/ai/picture-cap", data={"csrf": csrf, "picture_daily_cap": "9000"})
    assert scenario.app.db.one(cap, (erin.id,))["picture_daily_cap"] == 12  # type: ignore[index]
    assert "a number from 0 to 500" in (await site.get("/ai")).text
