"""D5a: `make dev` with the test fakes for every outside service, linked and kept.

`DevFakes` holds the fakes from `tests/fakes` (Google sign-in, Gmail, Calendar and Tasks
as local servers; the wall, ThinQ, Home Connect and travel as transports; Keep,
OurGroceries and Roborock at their interfaces) and hands them to `build_runtime` the way
the scenario harness hands them to `build_app` (`tests.fakes.wiring`).

On the first run it fills them (a washer and dryer, a dishwasher, a robot, the wall's
"Family" list) and links them through Themi's own link paths, so `data/dev/` holds real
linked accounts. What the fakes hold is saved in `data/dev/fakes.json` (each minute, after
each `act`, and on stop) and comes back on the next run, so Themi's sync cursors and
remote ids still match.

The fakes are only changed on Themi's event loop: `act` hands a change over from another
thread (the simulator's, D5b) and waits for it, so the fakes need no locks.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import parse_qs, urlparse

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.gtasks_api import FakeGtasks
from tests.fakes.home_connect import FakeHomeConnect
from tests.fakes.keep import MASTER_TOKEN, FakeKeep
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fakes.roborock import CODE as ROBOROCK_CODE
from tests.fakes.roborock import EMAIL as ROBOROCK_EMAIL
from tests.fakes.roborock import FakeRoborock
from tests.fakes.snapshot import Snapshots
from tests.fakes.thinq import TOKEN as THINQ_TOKEN
from tests.fakes.thinq import FakeThinq
from tests.fakes.travel import FakeTravel
from tests.fakes.wiring import connector_options, wall_list
from themi.accounts import Member
from themi.connectors.gkeep import KeepLogin
from themi.connectors.google import GoogleAccounts
from themi.connectors.homeconnect import HomeConnectAccount
from themi.core.keep_groceries import KeepLinks, new_device_id
from themi.storage.secrets import Secret

if TYPE_CHECKING:
    from themi.app import App
    from themi.scheduler import Scheduler

FAKES_FILE = "fakes.json"
SAVE_EVERY = timedelta(minutes=1)
ACT_TIMEOUT = 120.0  # seconds a change and its checks may take (triage asks the AI)
ADDRESSES = {"Erin": "erin@gmail.com", "Husband": "husband@gmail.com"}
WASHER, DRYER = "lg-washer-1", "lg-dryer-1"
DISHWASHER = "BOSCH-SMV-1"
ROBOT = "rr-duid-1"

T = TypeVar("T")
Check = str | Callable[[], Awaitable[object]]  # a periodic task's name, or a read


class DevFakes:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.google = FakeGoogle()
        self.gmail = FakeGmail(self.google)
        self.gcal = FakeGcal(self.google)
        self.gtasks = FakeGtasks(self.google)
        self.cozyla = FakeCozyla()
        self.thinq = FakeThinq()
        self.home_connect = FakeHomeConnect()
        self.roborock = FakeRoborock()
        self.keep = FakeKeep()
        self.ourgroceries = FakeOurGroceries()
        self.travel = FakeTravel()
        self.restored = False  # True when the fakes came back from the last run
        self.app: App | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._servers = (self.google, self.gmail, self.gcal, self.gtasks)

    def held(self) -> dict[str, Snapshots]:
        """Each fake by the name it's saved under."""
        return {
            "google": self.google,
            "gmail": self.gmail,
            "gcal": self.gcal,
            "gtasks": self.gtasks,
            "cozyla": self.cozyla,
            "thinq": self.thinq,
            "home_connect": self.home_connect,
            "roborock": self.roborock,
            "keep": self.keep,
            "ourgroceries": self.ourgroceries,
            "travel": self.travel,
        }

    # ----- starting and stopping --------------------------------------------------------

    def start(self, site_urls: list[str]) -> None:
        """Bring back the last run's state, if any, and start the local servers.

        `site_urls`: the dev website's addresses, whose Google callback the fake accepts
        (so relinking from the website works too)."""
        self.restored = self.load()
        self.google.state.redirect_uris |= {GoogleAccounts.redirect_uri(u) for u in site_urls}
        for server in self._servers:
            server.start()

    def stop(self) -> None:
        for server in self._servers:
            server.stop()

    def connectors(self, timezone: str) -> dict[str, Any]:
        return connector_options(
            google=self.google,
            gmail=self.gmail,
            gcal=self.gcal,
            gtasks=self.gtasks,
            ourgroceries=self.ourgroceries,
            cozyla=self.cozyla,
            travel=self.travel,
            home_connect=self.home_connect,
            thinq=self.thinq,
            roborock=self.roborock,
            keep=self.keep,
            timezone=timezone,
        )

    async def bind(self, app: App, site_url: str, scheduler: Scheduler | None = None) -> list[str]:
        """On Themi's loop, before it runs: link what isn't linked yet, and save each
        minute on `scheduler` (the runtime's). Returns what's linked, for the banner."""
        self.app = app
        self.loop = asyncio.get_running_loop()
        await self.link(app, site_url)
        if scheduler is not None:
            scheduler.every("dev.fakes_save", SAVE_EVERY, self._save_job)
        self.save()
        return self.linked()

    # ----- saving -----------------------------------------------------------------------

    def save(self) -> None:
        state = {name: fake.snapshot() for name, fake in self.held().items()}
        partial = self.path.with_suffix(".tmp")
        partial.write_text(json.dumps(state))
        os.replace(partial, self.path)

    def load(self) -> bool:
        if not self.path.exists():
            return False
        state = json.loads(self.path.read_text())
        for name, fake in self.held().items():
            if name in state:
                fake.restore(state[name])
        return True

    async def _save_job(self) -> None:
        self.save()

    # ----- changes from other threads ---------------------------------------------------

    def act(self, change: Callable[[], T], check: Check | Sequence[Check] = ()) -> T:
        """Make `change` to the fakes on Themi's loop and wait for it; then run `check` so
        Themi sees it now: periodic tasks by name, or reads of its own. Safe from any thread
        but Themi's own."""

        async def on_loop() -> T:
            result = change()
            self.save()
            for step in (check,) if isinstance(check, str) or callable(check) else check:
                await (self.check_now(step) if isinstance(step, str) else step())
            return result

        return self._on_loop(on_loop())

    def read(self, look: Callable[[], T]) -> T:
        """Read the fakes on Themi's loop (they're only changed there), from another thread."""

        async def on_loop() -> T:
            return look()

        return self._on_loop(on_loop())

    def _on_loop(self, work: Coroutine[Any, Any, T]) -> T:
        loop = self.loop
        if loop is None or _on(loop):
            work.close()
            raise RuntimeError(
                "act and read are for other threads while Themi runs; on its loop, use the fake"
            )
        return asyncio.run_coroutine_threadsafe(work, loop).result(ACT_TIMEOUT)

    async def check_now(self, task_name: str) -> object:
        """Run one of Themi's periodic tasks at once, as the scheduler would."""
        assert self.app is not None
        task = next((t for t in self.app.periodic if t.name == task_name), None)
        if task is None:
            raise KeyError(f"there's no periodic task called {task_name}")
        return await task.run()

    # ----- the first run's fill and links -----------------------------------------------

    def fill(self) -> None:
        """What the household has, on the first run (each step skipped if it's there)."""
        if WASHER not in self.thinq.devices:
            self.thinq.add_device(WASHER, "DEVICE_WASHER", "Washer")
            self.thinq.add_device(DRYER, "DEVICE_DRYER", "Dryer", "DLEX4000W")
        if DISHWASHER not in self.home_connect.appliances:
            self.home_connect.add_appliance(DISHWASHER, "Dishwasher", "Dishwasher")
        if ROBOT not in self.roborock.robots:
            self.roborock.add_robot(ROBOT, "Robbie")
        wall_list(self.cozyla)
        for address in ADDRESSES.values():
            self.keep.user(address)

    async def link(self, app: App, site_url: str) -> None:
        """Link each fake through Themi's own link path, unless it's linked already."""
        self.fill()
        store = app.store
        members = {m.name: m for m in store.list_members()}
        admin = next((m for m in members.values() if m.is_admin), None)
        services = app.services
        keep = KeepLinks(app.db, store.cipher)
        for name, address in ADDRESSES.items():
            member = members.get(name)
            if member is None:
                continue
            google_linked = store.linked_account_by_address("gmail", address) is not None
            if services.google is not None and not google_linked:
                await self._link_google(app, member, address, site_url)
            if not any(k.member_id == member.id for k in keep.all()):
                login = KeepLogin(address, Secret(MASTER_TOKEN), new_device_id())
                keep.link(member, login, "Shopping list")
        if admin is None:
            return
        if services.thinq is not None and not services.thinq.account.linked():
            await services.thinq.link(admin, THINQ_TOKEN, "US")
        if services.roborock is not None and not services.roborock.account.linked():
            await services.roborock.send_code(ROBOROCK_EMAIL)
            await services.roborock.link(admin, ROBOROCK_EMAIL, ROBOROCK_CODE)
        account, dishwasher = services.home_connect, services.dishwasher
        if account is not None and dishwasher is not None and not account.linked():
            redirect = HomeConnectAccount.redirect_uri(site_url)
            state, code = self.home_connect.approve(account.authorization_url(admin, redirect))
            await account.complete(state, code, redirect)
            await dishwasher.add_appliances(admin)

    async def _link_google(self, app: App, member: Member, address: str, site_url: str) -> None:
        """As if they linked Google from the website and tapped "Watch it": the inbox is
        watched from the start, without the setup question in the chat."""
        google = app.services.google
        assert google is not None
        redirect = GoogleAccounts.redirect_uri(site_url)
        url = google.oauth.authorization_url("link", redirect, member)
        callback = {
            k: v[0] for k, v in parse_qs(urlparse(self.google.consent(url, address)).query).items()
        }
        grant = await google.oauth.complete(callback["state"], callback["code"], redirect)
        listeners, google.link_listeners = google.link_listeners, []
        try:
            account = await google.link(grant)
        finally:
            google.link_listeners = listeners
        app.store.update_linked_account(member, account.id, watched=True)

    def linked(self) -> list[str]:
        """What's linked to the fakes, in words."""
        app = self.app
        if app is None:
            return []
        store = app.store
        found = [
            f"Google ({a.address})"
            for m in store.list_members()
            for a in store.linked_accounts(m.id)
        ]
        if KeepLinks(app.db, store.cipher).all():
            found.append("Keep")
        found += ["the wall", "OurGroceries"]
        found += [d.name for d in store.list_devices()]
        return found


def _on(loop: asyncio.AbstractEventLoop) -> bool:
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False
