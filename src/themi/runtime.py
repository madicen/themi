"""`themi run`: the Telegram poller, the scheduler and the website in one process.

Everything shares one asyncio loop. SIGTERM or SIGINT sets a stop event:
the poller stops at its next safe point (a batch being handled always
finishes), the scheduler finishes the job in progress, the HTTP server stops
accepting requests, and only then is the database closed.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import signal
import socket
import sys
from collections.abc import Awaitable, Callable, Coroutine
from datetime import timedelta
from typing import Any, NoReturn

import uvicorn

from themi import clock
from themi.app import App
from themi.scheduler import Scheduler
from themi.web import HealthSources, create_app, site_base_url
from themi.web.site import SiteContext

log = logging.getLogger(__name__)

SCHEDULER_TICK = timedelta(seconds=15)
SHUTDOWN_GRACE_SECONDS = 30
RESTART_AFTER_SECONDS = 1.0
CLOSE_TIMEOUT_SECONDS = 5.0  # each module's close, on the way out
LEFTOVER_GRACE_SECONDS = 5.0  # tasks still running once Themi has stopped


class PortInUse(Exception):
    """The website's port is taken (often by another Themi): said plainly, before anything
    else starts."""


def reexec() -> NoReturn:
    """SP6: start this same command again in this process (its PID stays, so in a
    container it's still PID 1 and Docker sees no exit). Called once Themi has stopped."""
    logging.shutdown()
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


async def close_all(closers: list[tuple[str, Callable[[], Awaitable[object]]]]) -> None:
    """What the modules keep open, closed in turn. One that fails or doesn't finish in
    CLOSE_TIMEOUT_SECONDS is logged and left, so the rest still close."""
    for name, close in closers:
        try:
            await asyncio.wait_for(close(), timeout=CLOSE_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning("%s didn't close in %ss; left open", name, CLOSE_TIMEOUT_SECONDS)
        except Exception:
            log.warning("%s didn't close cleanly", name, exc_info=True)


def run_to_end(main: Coroutine[Any, Any, object]) -> list[str]:
    """`asyncio.run(main)`, except that what's still running afterwards gets
    LEFTOVER_GRACE_SECONDS to stop rather than forever. asyncio.run cancels leftover tasks
    and waits for them, so one that ignores being cancelled (python-roborock's reconnect
    loop, 13 Nov 2026) kept Themi from ever exiting or restarting. Returns the names of the
    tasks left behind (logged too); what `main` raises is raised."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stuck: list[str] = []
    try:
        loop.run_until_complete(main)
    finally:
        try:
            stuck = _end_leftovers(loop)
            loop.run_until_complete(
                asyncio.wait_for(loop.shutdown_asyncgens(), LEFTOVER_GRACE_SECONDS)
            )
            loop.run_until_complete(
                asyncio.wait_for(loop.shutdown_default_executor(), LEFTOVER_GRACE_SECONDS)
            )
        except Exception:
            log.warning("Stopping the event loop didn't finish cleanly", exc_info=True)
        finally:
            asyncio.set_event_loop(None)
            if not stuck:
                loop.close()
    return stuck


def _end_leftovers(loop: asyncio.AbstractEventLoop) -> list[str]:
    leftovers = [task for task in asyncio.all_tasks(loop) if not task.done()]
    if not leftovers:
        return []
    for task in leftovers:
        task.cancel()
    loop.run_until_complete(asyncio.wait(leftovers, timeout=LEFTOVER_GRACE_SECONDS))
    for task in leftovers:
        if task.done() and not task.cancelled() and task.exception() is not None:
            log.warning("%s failed while stopping", task.get_name(), exc_info=task.exception())
    stuck = [task.get_name() for task in leftovers if not task.done()]
    for task in leftovers:
        if not task.done():
            log.warning(
                "%s (%s) didn't stop when cancelled; left behind",
                task.get_name(),
                getattr(task.get_coro(), "__qualname__", "?"),
            )
    return stuck


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
        self.restart_requested = False  # SP6: run again once stopped (`reexec`)
        app.services.restart = self.request_restart
        app.services.site_url = site_base_url(public_url, host, port)
        self.scheduler = app.scheduler or Scheduler(app.db)
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

    def request_restart(self) -> None:
        """SP6: stop as on SIGTERM, then start again (the caller re-executes the process).
        Soon, not now, so the page that asked gets its answer first."""
        self.restart_requested = True
        try:
            asyncio.get_running_loop().call_later(RESTART_AFTER_SECONDS, self.stop)
        except RuntimeError:  # no loop running: nothing to wait for
            self.stop()

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop)

    def _bind(self) -> socket.socket:
        """The website's socket, taken first: a port in use stops Themi with one plain line
        instead of uvicorn's exit after everything else has started."""
        config = self.server.config
        try:
            family = socket.AF_INET6 if ":" in config.host else socket.AF_INET
            return socket.create_server((config.host, config.port), family=family)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            raise PortInUse(
                f"Port {config.port} is already in use, perhaps by another Themi. Stop that, "
                "or give this one another port with THEMI_HTTP_PORT."
            ) from None

    async def run(self) -> None:
        sock = self._bind()
        if self.telegram_enabled:
            await self.app.channel.start()
            try:
                await self.app.channel.publish_commands(self.app.services.command_menu())
            except Exception:
                log.warning("Couldn't publish the command menu to Telegram", exc_info=True)
        else:
            log.warning("Telegram is disabled (THEMI_DISABLE_TELEGRAM); not polling")
        tasks = [
            asyncio.create_task(self.server.serve(sockets=[sock]), name="http"),
            asyncio.create_task(
                self.scheduler.run_forever(self.stop_event, self.scheduler_tick), name="scheduler"
            ),
        ]
        if self.telegram_enabled:
            tasks.append(
                asyncio.create_task(self.app.channel.run(self.stop_event), name="telegram")
            )
        log.info("Themi is running at %s", self.app.services.site_url)
        try:
            stopper = asyncio.create_task(self.stop_event.wait())
            waiting = {*tasks, stopper}
            while waiting:
                done, waiting = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                stop = stopper in done
                for task in done:
                    if task is stopper:
                        continue
                    if task.exception() is not None:
                        log.error(
                            "%s stopped unexpectedly", task.get_name(), exc_info=task.exception()
                        )
                        stop = True
                    elif task.get_name() != "telegram":
                        stop = True
                    # SP1: the channels finishing on their own (none of them polls, as in a
                    # Themi with only the website's chat) isn't a reason to stop.
                if stop:
                    break
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
        await close_all(self.app.services.closers)
        await self.app.outbox.flush()  # anything that became due while stopping
        self.app.db.close()
        log.info("Stopped")
