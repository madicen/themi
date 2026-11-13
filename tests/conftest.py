"""Shared pytest setup: markers, opt-in live/eval runs, and clock hygiene."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from themi import clock

# Shared fixtures every layer can use.
pytest_plugins = [
    "tests.fixtures.family",
    "tests.fakes.http_ai",
    "tests.fakes.telegram_api",
    "tests.fakes.slack_api",
    "tests.fakes.google_oauth",
    "tests.fakes.gmail_api",
    "tests.fakes.gcal_api",
    "tests.fakes.gtasks_api",
    "tests.fakes.cozyla",
    "tests.fakes.home_connect",
    "tests.fakes.spotify",
    "tests.fakes.thinq",
    "tests.fakes.roborock",
    "tests.fakes.tuya",
    "tests.fakes.catgenie",
    "tests.fakes.travel",
    "tests.fakes.weather",
    "tests.fakes.search",
    "tests.fakes.gdocs_api",
    "tests.fakes.gsheets_api",
    "tests.fakes.ourgroceries",
    "tests.fakes.keep",
    "tests.fakes.s3_api",
    "tests.fakes.server_runner",
    "tests.scenarios.harness",
    "tests.fixtures.web",
    "tests.fixtures.dev",
]

# Folder -> marker, so a test's layer is decided by where it lives.
LAYER_MARKERS = {
    "integration": "integration",
    "scenarios": "scenario",
    "live": "live",
    "evals": "eval",
}


STALE_TEMP = 3600  # seconds: a leftover this old is from a run that has ended


def pytest_sessionstart(session: pytest.Session) -> None:
    """Sweep the temp folders a crashed or killed run left behind (the browser tests'
    Chrome profiles and the step pictures of in-memory apps), so test runs can't slowly
    fill the disk (2026-11-10).
    Only ones older than an hour: a run going on at the same time keeps its own."""
    import shutil
    import tempfile
    import time
    from pathlib import Path

    if hasattr(session.config, "workerinput"):  # xdist: the controller sweeps, once
        return
    cutoff = time.time() - STALE_TEMP
    temp = Path(tempfile.gettempdir())
    for left in [*temp.glob("themi-chrome-*"), *temp.glob("themi-step-images-*")]:
        try:
            if left.is_dir() and left.stat().st_mtime < cutoff:
                shutil.rmtree(left, ignore_errors=True)
        except OSError:
            continue


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-live", action="store_true", help="run tests that hit real services")
    parser.addoption("--run-evals", action="store_true", help="run AI behaviour evals")
    parser.addoption(
        "--provider",
        default="gemini",
        help="for --run-evals: gemini, claude, ollama or openai_compat (see tests/evals/README.md)",
    )
    parser.addoption(
        "--repeat", type=int, default=1, help="for --run-evals: run each case this many times"
    )
    parser.addoption(
        "--routing",
        default="groups",
        choices=("groups", "all", "embeddings"),
        help="for --run-evals: the tool groups a message calls for (groups), every tool (all), "
        "or groups by meaning too (embeddings, P7b)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: modules together, fakes over real HTTP")
    config.addinivalue_line("markers", "scenario: end-to-end stories through the full stack")
    config.addinivalue_line("markers", "live: real services with test accounts (opt-in)")
    config.addinivalue_line("markers", "eval: AI behaviour evals per provider (opt-in)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_live = pytest.mark.skip(reason="live test: pass --run-live")
    skip_eval = pytest.mark.skip(reason="eval: pass --run-evals")
    for item in items:
        for folder, marker in LAYER_MARKERS.items():
            if f"/tests/{folder}/" in str(item.path).replace("\\", "/"):
                item.add_marker(marker)
        if "live" in item.keywords and not config.getoption("--run-live"):
            item.add_marker(skip_live)
        if "eval" in item.keywords and not config.getoption("--run-evals"):
            item.add_marker(skip_eval)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # A layer with no tests yet (e.g. evals before prompt 28) is not a failure.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK


@pytest.fixture(autouse=True)
def _reset_clock() -> Iterator[None]:
    """No test leaks a frozen clock into the next one."""
    yield
    clock.unfreeze()


@pytest.fixture
def frozen_clock() -> datetime:
    """Freeze time at a fixed, ordinary weekday morning (UTC) and return it."""
    start = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)  # Wed 09:00 in Pacific time
    clock.freeze(start)
    return start
