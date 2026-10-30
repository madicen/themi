"""Which real backend the evals run against, from the environment.

| PROVIDER      | Needs                                    | Optional                     |
| ------------- | ---------------------------------------- | ---------------------------- |
| gemini        | GEMINI_TEST_API_KEY (free tier is fine)  | THEMI_EVAL_MODEL (and below) |
| claude        | ANTHROPIC_API_KEY                        | THEMI_EVAL_MODEL             |
| ollama        | THEMI_EVAL_OLLAMA_MODEL                  | THEMI_EVAL_OLLAMA_URL        |
| openai_compat | THEMI_EVAL_OPENAI_URL, _MODEL            | THEMI_EVAL_OPENAI_KEY        |

THEMI_EVAL_PACE (seconds between cases) keeps free tiers under their rate
limits: 30 by default for Gemini (its free tier allowed 5 requests a minute and
20 a day for gemini-3.8-flash in October 2026; a case makes two or three), 0 for
the rest.

THEMI_EVAL_FALLBACK_MODEL adds a second backend after the first (the router
falls back to it, as in real use). THEMI_EVAL_RPM caps calls per minute for each
model: 10 by default for Gemini, unlimited otherwise.

These are read from the environment, then from `.env` (the environment wins),
so a test key can sit in `.env` instead of a shell history. Gemini's is
GEMINI_TEST_API_KEY, never GEMINI_API_KEY: that is the family's own key, which
sits in the same `.env`, and a run would spend their quota.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from themi.settings import read_dotenv
from themi.storage.secrets import Secret


@dataclass(frozen=True)
class EvalBackend:
    name: str
    kind: str
    model: str = ""
    base_url: str | None = None
    api_key: Secret | None = None
    pace: float = 0.0
    fallback_model: str = ""
    rpm: int = 0  # calls per minute per model; 0 is unlimited


def backend(name: str) -> EvalBackend | str:
    """The backend, or why it can't run (a skip reason)."""
    env = {**read_dotenv(Path(".env")), **os.environ}
    model = env.get("THEMI_EVAL_MODEL", "")
    pace = env.get("THEMI_EVAL_PACE")
    if name == "gemini":
        if not env.get("GEMINI_TEST_API_KEY"):
            return "set GEMINI_TEST_API_KEY to run the evals against Gemini"
        return EvalBackend(
            "gemini",
            "gemini",
            model,
            api_key=Secret(env["GEMINI_TEST_API_KEY"]),
            pace=float(pace or 0),
            fallback_model=env.get("THEMI_EVAL_FALLBACK_MODEL", ""),
            rpm=int(env.get("THEMI_EVAL_RPM") or 10),
        )
    if name == "claude":
        if not env.get("ANTHROPIC_API_KEY"):
            return "set ANTHROPIC_API_KEY to run the evals against Claude"
        return EvalBackend(
            "claude",
            "anthropic",
            model,
            api_key=Secret(env["ANTHROPIC_API_KEY"]),
            pace=float(pace or 0),
        )
    if name == "ollama":
        if not env.get("THEMI_EVAL_OLLAMA_MODEL"):
            return "set THEMI_EVAL_OLLAMA_MODEL to run the evals against Ollama"
        return EvalBackend(
            "ollama",
            "ollama",
            env["THEMI_EVAL_OLLAMA_MODEL"],
            base_url=env.get("THEMI_EVAL_OLLAMA_URL"),
            pace=float(pace or 0),
        )
    if name == "openai_compat":
        if not (env.get("THEMI_EVAL_OPENAI_URL") and env.get("THEMI_EVAL_OPENAI_MODEL")):
            return "set THEMI_EVAL_OPENAI_URL and THEMI_EVAL_OPENAI_MODEL"
        key = env.get("THEMI_EVAL_OPENAI_KEY")
        return EvalBackend(
            "openai_compat",
            "openai_compat",
            env["THEMI_EVAL_OPENAI_MODEL"],
            base_url=env["THEMI_EVAL_OPENAI_URL"],
            api_key=Secret(key) if key else None,
            pace=float(pace or 0),
        )
    return f"unknown provider {name!r}: gemini, claude, ollama or openai_compat"
