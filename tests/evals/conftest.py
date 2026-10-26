"""Eval plumbing: the chosen backend, and pass rates printed (and saved) at the end."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend, backend
from tests.evals.scoring import Outcome, format_summary, summarise

RESULTS_DIR = Path(__file__).with_name("results")
OUTCOMES: list[Outcome] = []


@pytest.fixture(scope="session")
def eval_backend(request: pytest.FixtureRequest) -> EvalBackend:
    chosen = backend(str(request.config.getoption("--provider")))
    if isinstance(chosen, str):
        pytest.skip(chosen)
    return chosen


@pytest.fixture(scope="session")
def eval_factory(eval_backend: EvalBackend) -> PacedFactory:
    """Shared by every case, so the per-minute limits span the whole run."""
    return PacedFactory(eval_backend.rpm)


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    if not OUTCOMES:
        return
    provider = str(config.getoption("--provider"))
    summary = summarise(OUTCOMES)
    terminalreporter.write_sep("=", "AI behaviour evals")
    terminalreporter.write_line(format_summary(provider, summary))
    for outcome in OUTCOMES:
        if not outcome.passed:
            terminalreporter.write_line(f"  {outcome.case.id}: {'; '.join(outcome.problems)}")
    RESULTS_DIR.mkdir(exist_ok=True)
    # The real date: this names a results file, it isn't app logic.
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    path = RESULTS_DIR / f"{provider}-{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "provider": provider,
                "summary": summary,
                "cases": [
                    {
                        "id": o.case.id,
                        "category": o.case.category,
                        "passed": o.passed,
                        "problems": o.problems,
                        "calls": o.calls,
                        "call_steps": o.call_steps,
                        "replies": o.replies,
                        "sent": o.sent,
                    }
                    for o in OUTCOMES
                ],
            },
            indent=2,
        )
    )
    terminalreporter.write_line(
        f"Saved {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}"
    )
