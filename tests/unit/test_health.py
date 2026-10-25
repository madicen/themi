from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from themi import clock
from themi.storage import open_database
from themi.web import HealthSources, create_app


@dataclass
class FakePoller:
    last_poll_at: datetime | None = None


def client(poller: FakePoller | None, started: datetime, db=None) -> TestClient:
    return TestClient(create_app(HealthSources(db or open_database(":memory:"), poller, started)))


def test_healthy_when_polling(frozen_clock: datetime) -> None:
    response = client(FakePoller(frozen_clock), frozen_clock).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "schema": "current",
        "telegram_poller": "alive",
    }


def test_starting_up_counts_as_healthy(frozen_clock: datetime) -> None:
    response = client(FakePoller(None), frozen_clock).get("/health")
    assert response.status_code == 200 and response.json()["telegram_poller"] == "starting"


def test_a_stalled_poller_is_unhealthy(frozen_clock: datetime) -> None:
    poller = FakePoller(frozen_clock)
    api = client(poller, frozen_clock)
    clock.advance(timedelta(minutes=3))
    response = api.get("/health")
    assert response.status_code == 503
    assert response.json()["telegram_poller"] == "stalled"


def test_telegram_disabled_is_reported(frozen_clock: datetime) -> None:
    response = client(None, frozen_clock).get("/health")
    assert response.status_code == 200 and response.json()["telegram_poller"] == "disabled"


def test_a_closed_database_is_unhealthy(frozen_clock: datetime) -> None:
    db = open_database(":memory:")
    db.close()
    response = client(FakePoller(frozen_clock), frozen_clock, db).get("/health")
    assert response.status_code == 503 and response.json()["database"] == "unreachable"


def test_an_unmigrated_database_is_unhealthy(frozen_clock: datetime) -> None:
    from themi.storage.db import Database

    response = client(FakePoller(frozen_clock), frozen_clock, Database(":memory:")).get("/health")
    assert response.status_code == 503 and response.json()["schema"] == "behind"


def test_no_api_docs_are_exposed(frozen_clock: datetime) -> None:
    api = client(None, frozen_clock)
    assert api.get("/docs").status_code == 404 and api.get("/openapi.json").status_code == 404
