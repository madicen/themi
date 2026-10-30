"""The evals' Gemini key is a test key, never the family's own GEMINI_API_KEY."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.evals.providers import EvalBackend, backend


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("GEMINI_API_KEY", "GEMINI_TEST_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / ".env"


def test_the_familys_key_alone_does_not_run_the_evals(env: Path) -> None:
    env.write_text("GEMINI_API_KEY=family-key\n")

    assert backend("gemini") == "set GEMINI_TEST_API_KEY to run the evals against Gemini"


def test_the_test_key_runs_them_even_beside_the_familys(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.write_text("GEMINI_API_KEY=family-key\nGEMINI_TEST_API_KEY=test-key\n")
    monkeypatch.setenv("GEMINI_API_KEY", "family-key-too")

    chosen = backend("gemini")

    assert isinstance(chosen, EvalBackend) and chosen.api_key is not None
    assert chosen.api_key.reveal() == "test-key"
