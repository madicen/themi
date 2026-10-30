"""Text to vectors (P7b), for routing a message to the tool groups it needs.

    embedder = RouterEmbedder(router)
    got = await embedder.embed(member.id, ["Going to lie down for a bit"])

`RouterEmbedder` goes through `themi.ai.router` as `AITask.EMBEDDING`, so the member's
own key, retries and fallback apply. `VectorCache` keeps vectors of fixed texts (the group
examples) by model, so a restart doesn't embed them again. Vectors are stored unit length,
so comparing two is a dot product.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Sequence
from typing import Protocol

from themi.ai.router import AIRouter
from themi.ai.settings import AITask
from themi.ai.types import CallKind, Embeddings
from themi.storage.db import Database

Vector = tuple[float, ...]


class Embedder(Protocol):
    async def embed(self, member_id: int, texts: Sequence[str]) -> Embeddings: ...


class RouterEmbedder:
    def __init__(self, router: AIRouter) -> None:
        self._router = router

    async def embed(self, member_id: int, texts: Sequence[str]) -> Embeddings:
        client = self._router.client_for(member_id, AITask.EMBEDDING)
        return await client.embed(texts, kind=CallKind.INTERACTIVE)


def unit(vector: Sequence[float]) -> Vector:
    length = math.sqrt(sum(x * x for x in vector))
    return tuple(x / length for x in vector) if length else tuple(vector)


def similarity(a: Vector, b: Vector) -> float:
    """Cosine similarity of two unit vectors."""
    return sum(x * y for x, y in zip(a, b, strict=True))


class VectorCache:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, model: str, texts: Sequence[str]) -> dict[str, Vector]:
        found: dict[str, Vector] = {}
        for text in dict.fromkeys(texts):
            blob = self.db.scalar(
                "SELECT vector FROM embedding_cache WHERE model = ? AND text = ?", (model, text)
            )
            if blob is not None:
                found[text] = tuple(array("f", blob))
        return found

    def put(self, model: str, texts: Sequence[str], vectors: Sequence[Vector]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO embedding_cache (model, text, vector) VALUES (?, ?, ?)",
            [
                (model, t, array("f", unit(v)).tobytes())
                for t, v in zip(texts, vectors, strict=True)
            ],
        )
