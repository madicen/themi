"""CR1: the check that core never imports a feature or a connector."""

from __future__ import annotations

from pathlib import Path

from tools.check_layers import KNOWN, breaches, problems

REPO_SRC = Path(__file__).resolve().parents[2] / "src"


def plant(src: Path, rel: str, text: str) -> None:
    path = src / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_real_code_has_only_the_known_breaches() -> None:
    assert problems(REPO_SRC) == []


def test_a_planted_import_is_caught(tmp_path: Path) -> None:
    plant(tmp_path, "themi/channels/outbox.py", "from themi_home.pantry import Pantry\n")
    plant(tmp_path, "themi/accounts/store.py", "import themi_google.connectors.gmail\n")
    plant(tmp_path, "themi/clock.py", "from themi.web import site\n")
    found = {(rel, module) for rel, _, module in breaches(tmp_path)}
    assert found == {
        ("themi/channels/outbox.py", "themi_home.pantry"),
        ("themi/accounts/store.py", "themi_google.connectors.gmail"),
        ("themi/clock.py", "themi.web"),
    }
    assert len(problems(tmp_path, known={})) == 3


def test_core_parts_still_in_themi_core_are_allowed(tmp_path: Path) -> None:
    plant(tmp_path, "themi/modules/context.py", "from themi.core.services import Services\n")
    plant(tmp_path, "themi/updates.py", "from themi.core.tools import tool\n")
    assert breaches(tmp_path) == []


def test_features_and_the_composition_root_are_not_checked(tmp_path: Path) -> None:
    plant(tmp_path, "themi/core/pantry.py", "from themi_google.connectors.gmail import GmailSync\n")
    plant(tmp_path, "themi/app.py", "from themi_home.pantry import Pantry\n")
    assert breaches(tmp_path) == []


def test_a_known_breach_that_is_gone_must_be_removed_from_the_list(tmp_path: Path) -> None:
    plant(tmp_path, "themi/clock.py", "import datetime\n")
    gone = problems(tmp_path, known={("themi/clock.py", "themi.core.x"): "CR9"})
    assert gone == [
        "themi/clock.py: no longer imports themi.core.x; remove it from KNOWN in "
        "tools/check_layers.py"
    ]


def test_every_known_breach_names_the_prompt_that_removes_it() -> None:
    assert all(prompt.startswith("CR") for prompt in KNOWN.values())
