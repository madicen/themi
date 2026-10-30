"""A fake embedding model: one axis per topic, so texts about the same topic point the same
way and the router's nearest-neighbour logic can be tested without a network.

    embed = TopicEmbedder({"settings": ("lie down", "rest", "nap"), "pantry": ("dinner",)})
    scenario.primary.embed_with = embed

A text's vector counts the phrases of each topic it contains, plus a little noise of its
own (seeded by the text), so texts with no topic words sit apart from every topic and from
each other.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

NOISE = 16  # extra dimensions


class TopicEmbedder:
    def __init__(self, topics: Mapping[str, Iterable[str]]) -> None:
        self.topics = {name: tuple(p.lower() for p in phrases) for name, phrases in topics.items()}

    def __call__(self, text: str) -> list[float]:
        said = text.lower()
        vector = [float(sum(p in said for p in phrases)) for phrases in self.topics.values()]
        seed = hashlib.sha256(said.encode()).digest()
        return [*vector, *((b - 127.5) / 1275 for b in seed[:NOISE])]  # each within 0.1
