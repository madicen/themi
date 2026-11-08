"""CR10a: code outside the home pack doesn't import it at runtime."""

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
    plant(tmp_path, "themi/core/tasks.py", "from themi.core.pantry import Pantry\n")
    plant(
        tmp_path,
        "themi/core/lists.py",
        "def f():\n    from themi.core.groceries import GroceryList\n",
    )
    plant(tmp_path, "themi/core/reminders.py", "from themi.core import recipes\n")
    found = problems(tmp_path)
    assert len(found) == 3
    assert (
        "themi/core/lists.py:2: the core code imports the home pack's themi.core.groceries"
        in (found[0])
    )


def test_a_type_only_import_the_home_pack_itself_and_the_root_are_fine(tmp_path: Path) -> None:
    plant(
        tmp_path,
        "themi/core/keys.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from themi.core.pantry import Pantry\n",
    )
    plant(tmp_path, "themi/core/meals.py", "from themi.core.pantry import Pantry\n")
    plant(tmp_path, "themi/app.py", "from themi.core.pantry import PantryModule\n")
    assert problems(tmp_path) == []


def test_the_google_pack_is_kept_too(tmp_path: Path) -> None:
    plant(tmp_path, "themi/core/tasks.py", "from themi.core.events import Events\n")
    plant(tmp_path, "themi/core/triage.py", "from themi.core.pantry import Pantry\n")
    plant(tmp_path, "themi/core/recipes.py", "from themi.connectors.google import GoogleAccounts\n")
    found = problems(tmp_path)
    assert len(found) == 2  # home may use Google; core and Google may not reach further
    assert any("the core code imports the google pack's themi.core.events" in f for f in found)
    assert any("the google code imports the home pack's themi.core.pantry" in f for f in found)
