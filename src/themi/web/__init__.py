"""Themi's HTTP side: the health check now, the management website from prompt 15."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from themi import clock
from themi.storage import migrations
from themi.storage.db import Database

PollerState = Literal["alive", "stalled", "starting", "disabled"]
# A healthy long poll returns at least every poll_timeout seconds; allow slack.
STALL_AFTER = timedelta(minutes=2)


class PollerStatus(Protocol):
    @property
    def last_poll_at(self) -> datetime | None: ...


@dataclass
class HealthSources:
    db: Database
    poller: PollerStatus | None  # None when Telegram is disabled
    started_at: datetime


def poller_state(sources: HealthSources, now: datetime) -> PollerState:
    if sources.poller is None:
        return "disabled"
    last = sources.poller.last_poll_at
    if last is None:
        return "starting" if now - sources.started_at < STALL_AFTER else "stalled"
    return "alive" if now - last < STALL_AFTER else "stalled"


def create_app(sources: HealthSources) -> FastAPI:
    app = FastAPI(title="Themi", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> JSONResponse:
        now = clock.now()
        try:
            sources.db.scalar("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        try:
            current = migrations.current_version(sources.db) if db_ok else -1
            latest = migrations.discover()[-1].version
            schema = "current" if current == latest else "behind"
        except Exception:
            schema = "unknown"
        poller = poller_state(sources, now)
        ok = db_ok and schema == "current" and poller in ("alive", "starting", "disabled")
        body = {
            "status": "ok" if ok else "degraded",
            "database": "ok" if db_ok else "unreachable",
            "schema": schema,
            "telegram_poller": poller,
        }
        return JSONResponse(body, status_code=200 if ok else 503)

    return app
