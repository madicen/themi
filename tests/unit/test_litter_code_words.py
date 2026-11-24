"""F60b (bug #261): what someone says the CatGenie app shows, as a message's words."""

from __future__ import annotations

import pytest

from themi_home.litter_box import code_words


@pytest.mark.parametrize(
    ("said", "words"),
    [
        ("Error: Drainage issue", "a drainage issue"),
        ("It says Error: Clogged waste", "a clogged waste error"),
        ('"Overheat"', "an overheat error"),
        ("UV lamp fault", "a UV lamp fault"),
        ("the dome is open", "the dome is open error"),
        ("  ", ""),
    ],
)
def test_code_words(said: str, words: str) -> None:
    assert code_words(said) == words
