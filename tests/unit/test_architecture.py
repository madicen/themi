"""Structural rules the codebase must keep, checked by reading the source."""

import ast
from pathlib import Path

from tools.check_clock import REPO_ROOT

SRC = REPO_ROOT / "src" / "themi"

# Only themi.ai may talk to model SDKs or build providers; everything else
# goes through themi.ai.router so per-member keys, retries and fallback apply.
AI_INTERNALS = ("anthropic", "openai", "google.genai", "themi.ai.adapters")


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_only_the_ai_package_reaches_model_sdks() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if (SRC / "ai") in path.parents:
            continue
        for module in imported_modules(path):
            if any(module == m or module.startswith(f"{m}.") for m in AI_INTERNALS):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
    assert offenders == [], "use themi.ai.router instead:\n" + "\n".join(offenders)


# Every message to a person goes through the outbox (quiet hours, limits, PDA
# shielding). Only the outbox and the channel itself may call send_text.
SEND_TEXT_ALLOWED = {
    SRC / "channels" / "outbox.py",
    SRC / "channels" / "telegram.py",
    SRC / "channels" / "channel_set.py",  # CR20b: the channels as one, handing on the outbox's
}


def test_only_the_outbox_sends_messages() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if path in SEND_TEXT_ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("send_text", "send_message", "edit_text")
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], "send through themi.channels.outbox:\n" + "\n".join(offenders)


# Energy is only ever shown as words. Nothing outside themi.energy may read the
# number (capacity()/combine()) to put it in front of anyone.
def test_capacity_numbers_stay_inside_the_energy_package() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if (SRC / "energy") in path.parents:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("capacity", "combine", "baseline")
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], "use EnergyModel.label() for anything people see:\n" + "\n".join(
        offenders
    )


def test_templates_never_mention_capacity_scores() -> None:
    # CR17b: the packs have page templates too; every one of them, in subfolders as well
    packs = ("themi", "themi_google", "themi_home")
    templates = [t for p in packs for t in (SRC.parent / p / "web" / "templates").rglob("*.html")]
    assert len(templates) > 40
    for template in templates:
        text = template.read_text().lower()
        assert "capacity" not in text and "score" not in text, template.name


# Every `themi` command reads the settings, so they must stay light: pulling in the
# outbox or Telegram there once cost two seconds per command.
def test_reading_settings_stays_light() -> None:
    import subprocess
    import sys

    code = (
        "import sys, themi.settings, themi.cli; "
        "heavy = [m for m in ('themi.channels.outbox', 'telegram', 'themi.app') "
        "if m in sys.modules]; print(heavy)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    )
    assert result.stdout.strip() == "[]"


# CR21b: displays (the Cozyla wall) are mirrors the standard modules know only through
# themi.modules.mirrors; none names Cozyla or the wall ("wall-clock" is a time).
def test_no_standard_module_names_cozyla_or_the_wall() -> None:
    import re

    named = re.compile(r"cozyla|\bwall(?!-clock)|wall_|_wall\b", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{n}"
        for path in sorted((SRC / "standard").rglob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if named.search(line)
    ]
    assert offenders == []
