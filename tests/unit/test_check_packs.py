"""CR10a, CR10b1, CR10b2: the core doesn't import a pack, and Google doesn't import home."""

from __future__ import annotations

from pathlib import Path

from tools.check_packs import problems

REPO_SRC = Path(__file__).resolve().parents[2] / "src"


def plant(src: Path, rel: str, text: str) -> None:
    path = src / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_real_code_keeps_to_it() -> None:
    assert problems(REPO_SRC) == []


def test_a_runtime_import_is_caught_wherever_it_is(tmp_path: Path) -> None:
    plant(tmp_path, "themi/standard/tasks.py", "from themi_home.pantry import Pantry\n")
    plant(
        tmp_path,
        "themi/standard/lists.py",
        "def f():\n    from themi_home.groceries import GroceryList\n",
    )
    plant(tmp_path, "themi/core/agent.py", "import themi_google.events\n")
    found = problems(tmp_path)
    assert len(found) == 3
    assert any(
        "themi/standard/lists.py:2: the core code imports the home pack's themi_home.groceries" in f
        for f in found
    )


def test_a_type_only_import_a_packs_own_code_and_the_root_are_fine(tmp_path: Path) -> None:
    plant(
        tmp_path,
        "themi/core/keys.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from themi_home.pantry import Pantry\n",
    )
    plant(tmp_path, "themi_home/meals.py", "from themi_home.pantry import Pantry\n")
    plant(tmp_path, "themi/app.py", "from themi_home.pantry import PantryModule\n")
    assert problems(tmp_path) == []


def test_home_may_use_google_and_google_may_not_use_home(tmp_path: Path) -> None:
    plant(tmp_path, "themi_home/recipes.py", "from themi_google.connectors.google import X\n")
    plant(tmp_path, "themi_google/triage.py", "from themi_home.pantry import Pantry\n")
    found = problems(tmp_path)
    assert found == [
        "themi_google/triage.py:1: the google code imports the home pack's themi_home.pantry"
    ]
