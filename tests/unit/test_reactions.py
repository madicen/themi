"""S5: the pieces that turn reactions into words."""

from __future__ import annotations

from themi.core.reactions import _lean, length_word, verdict


def test_which_reactions_count() -> None:
    assert [verdict((e,)) for e in ("👍", "❤", "❤️", "🙏", "👎", "😕", "🔥", "✅")] == [
        1, 1, 1, 1, -1, -1, 0, 0,
    ]  # fmt: skip
    assert verdict(("🔥", "👎")) == -1  # the first that counts


def test_lengths_in_words() -> None:
    assert length_word("Water the plants?") == "short"
    assert length_word("x" * 300) == "medium-length"
    assert length_word("x" * 501) == "long"


def test_a_lean_needs_three_and_a_clear_majority() -> None:
    assert _lean([1, 1]) is None
    assert _lean([1, 1, -1]) == 1
    assert _lean([1, -1, -1]) == -1
    assert _lean([1, 1, -1, -1]) == -1  # half not landing is enough to say so
    assert _lean([1, 1, 1, -1, -1]) is None
