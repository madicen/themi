"""F60a (bug #260): a message names a routine item, a transcriber's slip and all."""

from __future__ import annotations

import pytest

from themi.core.wording import names_title


@pytest.mark.parametrize(
    ("said", "title"),
    [
        ("Check off take meds.", "Take Meds"),
        ("Check off tick meds.", "Take Meds"),  # reply 554: heard "tick"
        ("I flossed", "Floss"),
        ("cover the birdcage please", "Cover the birdcage"),
        ("did cycle the dishwasher", "Cycle Dishwasher"),
    ],
)
def test_named(said: str, title: str) -> None:
    assert names_title(said, title)


@pytest.mark.parametrize(
    ("said", "title"),
    [
        ("check off the meds", "Take Meds"),  # one word missing, not misheard
        ("take the dog out", "Take Meds"),
        ("fluss", "Floss"),  # a one-word title is never guessed
        ("what time is it", "Take Meds"),
        ("tick off the dishes", "Cycle Dishwasher"),
        ("", "Take Meds"),
    ],
)
def test_not_named(said: str, title: str) -> None:
    assert not names_title(said, title)
