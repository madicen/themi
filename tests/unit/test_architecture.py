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
