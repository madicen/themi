"""`themi run`: the Telegram poller, the scheduler and the website in one process.

Everything shares one asyncio loop. SIGTERM or SIGINT sets a stop event:
the poller stops at its next safe point (a batch being handled always
finishes), the scheduler finishes the job in progress, the HTTP server stops
accepting requests, and only then is the database closed.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import timedelta

import uvicorn

from themi import clock
from themi.app import App
from themi.scheduler import Scheduler
from themi.web import HealthSources, create_app, site_base_url
from themi.web.site import SiteContext

log = logging.getLogger(__name__)

SCHEDULER_TICK = timedelta(seconds=15)
SHUTDOWN_GRACE_SECONDS = 30


class Runtime:
    def __init__(
        self,
        app: App,
        *,
        host: str,
        port: int,
        telegram_enabled: bool = True,
        scheduler_tick: timedelta = SCHEDULER_TICK,
        public_url: str = "",
    ) -> None:
        self.app = app
        self.telegram_enabled = telegram_enabled
        self.scheduler_tick = scheduler_tick
        self.stop_event = asyncio.Event()
        app.services.site_url = site_base_url(public_url, host, port)
        self.scheduler = Scheduler(app.db)
        for task in app.periodic:
            self.scheduler.every(task.name, task.every, task.run)
        self.web = create_app(
            HealthSources(app.db, app.channel if telegram_enabled else None, clock.now()),
            SiteContext(
                app,
                base_url=site_base_url(public_url, host, port),
                secure_cookies=public_url.startswith("https://"),
            ),
        )
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.web,
                host=host,
                port=port,
                lifespan="off",
                log_config=None,
                access_log=False,
            )
        )

    @property
    def port(self) -> int | None:
        """The port actually bound (useful when configured as 0)."""
        servers = getattr(self.server, "servers", None)
        if not servers:
            return None
        return servers[0].sockets[0].getsockname()[1]

    def stop(self) -> None:
        self.stop_event.set()

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop)

    async def run(self) -> None:
        if self.telegram_enabled:
            await self.app.channel.start()
            try:
                await self.app.channel.publish_commands(self.app.services.command_menu())
            except Exception:
                log.warning("Couldn't publish the command menu to Telegram", exc_info=True)
        else:
            log.warning("Telegram is disabled (THEMI_DISABLE_TELEGRAM); not polling")
        tasks = [
            asyncio.create_task(self.server.serve(), name="http"),
            asyncio.create_task(
                self.scheduler.run_forever(self.stop_event, self.scheduler_tick), name="scheduler"
            ),
        ]
        if self.telegram_enabled:
            tasks.append(
                asyncio.create_task(self.app.channel.run(self.stop_event), name="telegram")
            )
        log.info("Themi is running")
        try:
            stopper = asyncio.create_task(self.stop_event.wait())
            done, _ = await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopper and task.exception() is not None:
                    log.error("%s stopped unexpectedly", task.get_name(), exc_info=task.exception())
        finally:
            await self._shutdown(tasks)

    async def _shutdown(self, tasks: list[asyncio.Task]) -> None:
        log.info("Shutting down")
        self.stop_event.set()
        self.server.should_exit = True
        _, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_GRACE_SECONDS)
        for task in pending:
            log.warning("%s didn't stop in time; cancelling it", task.get_name())
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if self.telegram_enabled:
            try:
                await self.app.channel.stop()
            except Exception:
                log.warning("Telegram client didn't close cleanly", exc_info=True)
        await self.app.outbox.flush()  # anything that became due while stopping
        self.app.db.close()
        log.info("Stopped")
