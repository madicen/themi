"""SP7a: from a brand-new Themi to chatting with it, with only the website."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.wiring import WALL_LIST, connector_options
from tests.fixtures.family import seed_family
from tests.fixtures.web import csrf_of, sign_in, web_client
from tests.scenarios.harness import ModelBank
from tests.scenarios.test_web_chat import said, scripted
from themi.accounts import AccountStore
from themi.accounts.claim import CODE_FILE, Claim
from themi.app import build_app, family_modules
from themi.cli import build_runtime
from themi.config import load_config
from themi.runtime import Runtime
from themi.settings import Settings, ensure_secret_key
from themi.standard.web_chat import WebChatModule
from themi.storage import open_database


def new_themi(tmp_path: Path) -> tuple[SimpleNamespace, ModelBank, str]:
    env = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    assert ensure_secret_key(env) is not None  # a new Themi makes its own key
    settings = Settings.from_mapping(env)
    db = open_database(settings.db_path)
    models = ModelBank()
    modules = [m for m in family_modules() if m.name != "telegram"] + [WebChatModule()]
    app = build_app(db, settings.cipher(), None, provider_factory=models, modules=modules)
    app.services.settings = settings
    app.services.environment = env
    code = Claim(AccountStore(db, settings.cipher())).make(tmp_path)
    return SimpleNamespace(app=app), models, code


async def test_a_new_themi_is_claimed_set_up_and_chatted_with(tmp_path: Path) -> None:
    themi, models, code = new_themi(tmp_path)
    app = themi.app
    async with web_client(themi) as site:  # type: ignore[arg-type]
        first = await site.get("/", follow_redirects=True)
        assert str(first.url).endswith("/claim") and "Enter its claim code" in first.text
        wrong = await site.post(
            "/claim",
            data={"code": "AAAA-AAAA", "household": "The Smiths", "timezone": "UTC", "name": "Sam"},
        )
        assert wrong.status_code == 400 and "isn&#39;t the code" in wrong.text
        assert 'value="The Smiths"' in wrong.text  # what they typed stays
        claimed = await site.post(
            "/claim",
            data={"code": code, "household": "The Smiths", "timezone": "UTC", "name": "Sam"},
        )
        assert claimed.headers["location"] == "/claim/key"
        key_page = (await site.get("/claim/key")).text
        key = (tmp_path / "secret.key").read_text().strip()
        assert key in key_page and "Without it, a backup can't be read." in key_page
        await site.post("/claim/key", data={"csrf": csrf_of(key_page)})
        home = (await site.get("/")).text
        assert "Finish setting up Themi" in home
        assert "Set up a way to chat from a phone, like Telegram." in home
        assert (await site.get("/claim/key")).headers["location"] == "/"  # shown once
        assert (await site.get("/claim")).headers["location"] == "/"
        sam = app.store.member_by_name("Sam")
        assert sam is not None and sam.is_admin
        scripted(app, sam, models)  # Sam's AI key, as the AI page would add it
        models["primary"].queue_text("Hi Sam. I'm ready when you are.")
        csrf = csrf_of(home)
        await site.post("/chat", data={"csrf": csrf, "text": "Hello"})
        await app.outbox.flush()
        chat = (await site.get("/chat")).text
    assert said(chat)[-2:] == ["Hello", "Hi Sam. I&#39;m ready when you are."]
    assert not (tmp_path / CODE_FILE).exists()


async def test_without_a_key_made_by_themi_there_is_no_key_page(tmp_path: Path) -> None:
    themi, _, code = new_themi(tmp_path)
    themi.app.services.environment = {**themi.app.services.environment, "THEMI_SECRET_KEY": "x"}
    async with web_client(themi) as site:  # type: ignore[arg-type]
        claimed = await site.post(
            "/claim", data={"code": code, "household": "H", "timezone": "UTC", "name": "Sam"}
        )
        assert claimed.headers["location"] == "/"


async def test_a_claimed_themi_never_asks_again(tmp_path: Path) -> None:
    themi, _, code = new_themi(tmp_path)
    async with web_client(themi) as site:  # type: ignore[arg-type]
        await site.post(
            "/claim", data={"code": code, "household": "H", "timezone": "UTC", "name": "Sam"}
        )
    async with web_client(themi) as other:  # type: ignore[arg-type]
        again = await other.post(
            "/claim", data={"code": code, "household": "X", "timezone": "UTC", "name": "Eve"}
        )
        assert again.headers["location"] == "/"
        signed_out = await other.get("/signed-out")
        assert signed_out.status_code == 200 and re.search("signed out", signed_out.text)
    assert themi.app.store.member_by_name("Eve") is None


async def test_modules_wait_for_the_claim_before_their_jobs_run(
    tmp_path: Path, fake_cozyla: FakeCozyla
) -> None:
    """Settings in .env can turn a module on before anyone claims Themi. Its jobs wait
    for the family: with no members there's nobody for them to act for."""
    env = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    assert ensure_secret_key(env) is not None
    settings = Settings.from_mapping(env)
    db = open_database(settings.db_path)
    modules = [
        m for m in family_modules(**connector_options(cozyla=fake_cozyla)) if m.name != "telegram"
    ]
    app = build_app(db, settings.cipher(), None, modules=modules)
    fake_cozyla.add_todo(fake_cozyla.add_list(WALL_LIST), "Water the plants")  # nobody's
    claim = Claim(AccountStore(db, settings.cipher()))
    code = claim.make(tmp_path)

    assert app.scheduler is not None
    for task in app.periodic:  # as the Runtime adds them
        app.scheduler.every(task.name, task.every, task.run)
    report = await app.scheduler.run_due()
    assert "cozyla.sync" in report.periodic and report.failures == []
    assert fake_cozyla.paths() == []  # the wall isn't even asked yet

    sam = claim.claim(code, "The Smiths", "UTC", "Sam", tmp_path)
    await next(t for t in app.periodic if t.name == "cozyla.sync").run()
    assert fake_cozyla.paths() != []
    assert db.query("SELECT title, default_owner FROM tasks") == [
        {"title": "Water the plants", "default_owner": sam.id}
    ]


def started(tmp_path: Path, **more: str) -> Runtime:
    """`themi run` on a data folder, as the container starts it."""
    env = {"THEMI_DB_PATH": str(tmp_path / "themi.db"), "THEMI_DISABLE_TELEGRAM": "1", **more}
    ensure_secret_key(env)
    return build_runtime(Settings.from_mapping(env))


def test_a_new_themi_starts_with_only_its_core_and_the_web_chat(tmp_path: Path) -> None:
    """The setup portal plan: a fresh Themi starts with the core and the web chat, and the
    admin builds it up on the Modules page. Settings in .env don't bring the family's in."""
    runtime = started(tmp_path, COZYLA_EMAIL="a@b.c", COZYLA_PASSWORD="x", COZYLA_TODO_LIST="F")
    names = {m.name for m in runtime.app.modules}
    assert "web_chat" in names
    assert not names & {"body_double", "chore_chart", "cozyla_todos", "tasks", "telegram"}
    written = load_config(tmp_path / "themi.toml")  # so it stays that way once claimed
    assert (written.template, written.added) == ("empty", ("web_chat",))


def test_a_claimed_themi_keeps_what_it_was_started_with(tmp_path: Path) -> None:
    first = started(tmp_path)
    claim = Claim(first.app.store)
    claim.claim(claim.make(tmp_path), "Sam's work", "UTC", "Sam", tmp_path)
    first.app.db.close()
    again = started(tmp_path)
    assert again.app.services.start_report.template == "empty"


def test_a_family_without_themi_toml_stays_the_family(tmp_path: Path) -> None:
    """An install from before the setup portal has a family and no themi.toml."""
    env = {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    ensure_secret_key(env)
    settings = Settings.from_mapping(env)
    seed_family(AccountStore(open_database(settings.db_path), settings.cipher()))
    runtime = started(tmp_path)
    assert runtime.app.services.start_report.template == "family"
    assert "body_double" in {m.name for m in runtime.app.modules}
    assert not (tmp_path / "themi.toml").exists()


async def test_a_new_themis_settings_are_only_the_cores(tmp_path: Path) -> None:
    """No rows for modules that aren't on: body double, the chore chart, the day summary."""
    runtime = started(tmp_path)
    claim = Claim(runtime.app.store)
    claim.claim(claim.make(tmp_path), "Sam's work", "UTC", "Sam", tmp_path)
    runtime.app.services.settings = Settings.from_mapping(
        {"THEMI_DB_PATH": str(tmp_path / "themi.db")}
    )
    sam = runtime.app.store.member_by_name("Sam")
    assert sam is not None
    themi = SimpleNamespace(app=runtime.app, member=lambda _: sam)
    async with web_client(themi) as site:  # type: ignore[arg-type]
        await sign_in(themi, site, "Sam")  # type: ignore[arg-type]
        page = (await site.get("/settings")).text
        home = (await site.get("/")).text
        more = (await site.get("/more")).text
    assert 'href="/more"' in home  # the bar: Home and More (at the bottom, on a phone)
    assert 'href="/modules"' in more  # the claimant is an admin
    titles = re.findall(r'<span class="row-title">([^<]+)</span>', page)
    assert "Quiet hours" in titles
    assert not set(titles) & {
        "Body double",
        "My chore chart",
        "Good-morning message",
        "My calendars",
    }


async def test_a_new_themis_menu_is_for_setting_it_up(tmp_path: Path) -> None:
    """Nothing in the menu for modules that aren't on; Modules and Development on the
    admin's bar and in their name's menu; "People", not "Family", off the family template."""
    runtime = started(tmp_path)
    claim = Claim(runtime.app.store)
    sam = claim.claim(claim.make(tmp_path), "Sam's work", "UTC", "Sam", tmp_path)
    themi = SimpleNamespace(app=runtime.app, member=lambda _: sam)
    async with web_client(themi) as site:  # type: ignore[arg-type]
        await sign_in(themi, site, "Sam")  # type: ignore[arg-type]
        home = (await site.get("/")).text
        more = (await site.get("/more")).text
        people = (await site.get("/family")).text
    bar = home[home.index('<nav class="tabs"') : home.index("</nav>")]
    assert re.findall(r'href="([^"]+)"', bar) == ["/", "/modules", "/dev", "/more"]
    menu = home[home.index('<details class="menu">') :]
    assert '<a href="/modules">Modules</a>' in menu[: menu.index("</details>")]
    groups = re.findall(r"<h2>([^<]+)</h2>", more)
    assert "Household" not in groups and "This Themi" in groups
    titles = re.findall(r'<span class="row-title">([^<]+)</span>', more)
    assert "People" in titles and "Family" not in titles
    assert not {"Google accounts", "Household connections"} & set(titles)
    assert "<h1>People</h1>" in people and "Appliances, the vacuum" not in people
