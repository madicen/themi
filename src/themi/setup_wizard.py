"""`themi setup`: what this Themi is made of, written to themi.toml and .env (CR11).

It asks for the core's settings (the website's address; it makes the secret key), a
template, then (CR19) by kind, in order: how they'll talk to Themi (channels), the AI
providers (at least one), the capabilities (voice notes, pictures, making pictures), then
services and features. Each step says what the template has, which to leave out and which
to add (with what those need). Then each module's own settings. Plain answers go to
themi.toml, secrets to .env (readable only by its owner). Then it tries each module that
has something to try against its service, and lists what's left to do on the website.
`--check` tries an existing setup again.

It never overwrites a file without asking, and a blank answer leaves a setting unset.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from themi.config import (
    available_modules,
    load_config,
    load_template,
    resolve_modules,
    template_packages,
)
from themi.modules import Module
from themi.modules.settings import questions
from themi.settings import Settings, SettingsError, read_dotenv
from themi.storage.secrets import generate_key

Ask = Callable[[str, str | None], str]  # (question, default) -> the answer as typed
AskSecret = Callable[[str], str]  # (question) -> the answer, not shown as it's typed
Say = Callable[[str], None]
Run = Callable[[Coroutine[Any, Any, str | None]], str | None]

YES = ("y", "yes", "true", "1", "on")
KEY_NOTE = """Made a secret key for what Themi keeps encrypted.
Keep .env backed up: without it, the data can't be read."""


class SetupCancelled(Exception):
    """They chose not to replace a file; nothing was written."""


@dataclass
class Answers:
    template: str = "family"
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    sections: dict[str, dict[str, object]] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


def templates() -> list[str]:
    return sorted(template_packages())


def run_setup(
    ask: Ask,
    ask_secret: AskSecret,
    say: Say,
    out_dir: Path,
    *,
    known: dict[str, type[Module]] | None = None,
    run: Run = asyncio.run,
) -> tuple[Path, Path]:
    """Ask, write themi.toml and .env into `out_dir`, try the modules, and say what's left.
    Returns the two files' paths."""
    known = available_modules() if known is None else known
    answers = Answers()
    say("Setting up a Themi. A blank answer leaves a setting unset; you can add it later.")

    # ----- the core (CR20b: Telegram's token is the telegram module's, asked with it) ------
    answers.env["THEMI_SECRET_KEY"] = generate_key()
    say(KEY_NOTE)
    public = ask("The website's public address (blank: this machine only)", None).strip()
    if public:
        answers.env["THEMI_PUBLIC_URL"] = public.rstrip("/")

    # ----- the template and its modules -------------------------------------------------------
    names = templates()
    say(f"Templates: {', '.join(names)}.")
    while True:
        chosen = ask("Which template", "family").strip() or "family"
        if chosen in names:
            break
        say(f"There's no template called {chosen}. The templates are {', '.join(names)}.")
    answers.template = chosen
    template = load_template(chosen)
    modules = list(template.modules)
    # CR19: by kind, in order: how they'll talk to Themi, the AI, what it can do, the rest.
    for step in STEPS:
        modules = _ask_kind(ask, say, step, chosen, modules, known, answers)
    for name in list(modules):  # what they need comes too, said once each
        for need in _needs(name, known):
            if need not in modules:
                modules.append(need)
                answers.added.append(need)
                say(f"{need} is added too: {name} needs it.")

    # ----- each module's own settings: each model asked once (both wall modules share one) ----
    asked_models: dict[type, dict[str, object]] = {}
    for name in modules:
        model = known[name].settings
        if model is None or not questions(model):
            continue
        if model in asked_models:  # asked already, for another module: the same answers
            if asked_models[model]:
                answers.sections[name] = dict(asked_models[model])
            continue
        say(f"{name}:")
        plain: dict[str, object] = {}
        for field_name, variable, question, secret, help_text in questions(model):
            if help_text:
                say(f"  ({help_text})")
            if secret:
                value = ask_secret(f"  {question}").strip()
                if value:
                    answers.env[variable] = value
                continue
            value = ask(f"  {question}", None).strip()
            if value:
                is_bool = model.model_fields[field_name].annotation is bool
                plain[field_name] = value.lower() in YES if is_bool else value
        asked_models[model] = plain
        if plain:
            answers.sections[name] = dict(plain)

    toml_path, env_path = write_files(answers, out_dir, ask, say)
    say(f"Wrote {toml_path} and {env_path}.")
    check_setup(out_dir, say, known=known, run=run)
    return toml_path, env_path


@dataclass(frozen=True)
class Step:
    kinds: tuple[str, ...]
    heading: str  # what the step is about, said first
    leave_out: str  # the questions; distinct per step, so each answer goes to its own
    add: str


STEPS = (
    Step(
        ("channel",), "How you'll talk to Themi", "Leave out any channels", "Which other channels"
    ),
    Step(("ai",), "AI providers", "Leave out any AI providers", "Which other AI providers"),
    Step(
        ("capability",),
        "What Themi can do with voice notes and pictures, and make",
        "Leave out any capabilities",
        "Which other capabilities",
    ),
    Step(("connector", "feature"), "Services and features", "Leave any out", "Add any"),
)
AI_FALLBACK = "gemini"  # its free tier is every member's first backend


def _ask_kind(
    ask: Ask,
    say: Say,
    step: Step,
    template: str,
    modules: list[str],
    known: dict[str, type[Module]],
    answers: Answers,
) -> list[str]:
    """One kind's step: what the template has of it, leave any out, add others."""
    mine = [m for m in modules if m in known and known[m].kind in step.kinds]
    others = [m for m in sorted(known) if known[m].kind in step.kinds and m not in modules]
    if not mine and not others:
        return modules
    say(f"{step.heading}. The {template} template has: {', '.join(mine) or 'none'}.")
    question = f"{step.leave_out} (names, with commas; blank: none)"
    removed = _pick(ask, say, question, mine) if mine else []
    if others:
        say(f"Also available: {', '.join(others)}.")
    added = _pick(ask, say, f"{step.add} (names, with commas; blank: none)", others)
    if "ai" in step.kinds and not [m for m in mine if m not in removed] and not added:
        if AI_FALLBACK in removed:
            removed.remove(AI_FALLBACK)
        else:
            added.append(AI_FALLBACK)
        say(f"A Themi needs at least one AI provider, so it keeps {AI_FALLBACK}.")
    answers.removed += removed
    answers.added += added
    return [m for m in modules if m not in removed] + added


def _pick(ask: Ask, say: Say, question: str, choices: list[str]) -> list[str]:
    while True:
        said = [n.strip() for n in ask(question, None).split(",") if n.strip()]
        unknown = [n for n in said if n not in choices]
        if not unknown:
            return said
        say(f"Not one of these: {', '.join(unknown)}.")


def _needs(name: str, known: dict[str, type[Module]]) -> list[str]:
    out: list[str] = []
    for need in known[name].requires:
        out += [n for n in (*_needs(need, known), need) if n not in out]
    return out


def write_files(answers: Answers, out_dir: Path, ask: Ask, say: Say) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    toml_path, env_path = out_dir / "themi.toml", out_dir / ".env"
    for path in (toml_path, env_path):
        if (
            path.exists()
            and ask(f"{path} is there already. Replace it (yes or no)", "no").strip().lower()
            not in YES
        ):
            say("Left as it was; nothing was written.")
            raise SetupCancelled(str(path))
    toml_path.write_text(as_toml(answers))
    env_path.write_text("".join(f"{k}={v}\n" for k, v in answers.env.items()))
    env_path.chmod(0o600)
    return toml_path, env_path


def as_toml(answers: Answers) -> str:
    lines = [
        "# What this Themi is made of: written by `themi setup`. Secrets are in .env.",
        f"template = {json.dumps(answers.template)}",
    ]
    changes = [f"+{n}" for n in answers.added] + [f"-{n}" for n in answers.removed]
    if changes:
        lines.append(f"modules = {json.dumps(changes)}")
    for name, values in answers.sections.items():
        lines += ["", f"[module.{name}]"]
        lines += [f"{key} = {json.dumps(value)}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def check_setup(
    out_dir: Path,
    say: Say,
    *,
    known: dict[str, type[Module]] | None = None,
    run: Run = asyncio.run,
) -> int:
    """Try a setup's modules against their services, and say what's left to do on the
    website. Returns how many problems there were."""
    env = read_dotenv(out_dir / ".env")
    try:
        settings = Settings.from_mapping(env)
        modules = resolve_modules(load_config(out_dir / "themi.toml"), settings, known)
    except SettingsError as exc:
        say(str(exc))
        return 1
    problems = 0
    for module in modules:
        try:
            problem = run(module.check())
        except Exception as exc:  # a check that broke is a problem too, said plainly
            problem = f"couldn't be tried: {exc}"
        if problem:
            problems += 1
            say(f"{module.name}: {problem}")
    say("Everything that could be tried worked." if not problems else f"{problems} to look at.")
    left = [f"- {type(m).website}" for m in modules if type(m).website]
    if left:
        say("Still to do once Themi is running:\n" + "\n".join(dict.fromkeys(left)))
    return problems
