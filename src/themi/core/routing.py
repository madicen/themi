"""P7b: which tool groups a message needs, by meaning as well as by words.

With `THEMI_TOOL_ROUTING=embeddings` the word lists (`choose_groups`) still run, and two
things add to what they pick:

- `EmbeddingRouter.choose`: the message (and the person's last two) become vectors, and
  every group with an example (`GROUP_EXAMPLES`) at least `THRESHOLD` similar is sent. No
  training: nearest neighbours. Every group above the line, not just the best, and each
  clause of a message is embedded too, since a vector of "need a nap, then what's for
  dinner?" sits between the two: two asks bring two groups. The examples' vectors are
  embedded once per model and cached.
- `recent_groups`: the groups whose tools ran in the person's last few replies, since short
  follow-ups ("and butter") carry too little for either method.

Routing never costs a reply: if embedding fails or takes over `TIMEOUT` seconds, the word
lists decide alone (the examples keep warming in the background), and `more_tools` stays.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence

from themi import clock
from themi.ai.embeddings import Embedder, Vector, VectorCache, similarity, unit
from themi.core.tools import GROUP_EXAMPLES, TOOL_GROUPS, more_tools
from themi.storage.db import Database

log = logging.getLogger(__name__)

# From tests/evals/test_router_thresholds.py on 2026-10-30, with the word lists: 0.725 sent
# what 108 of 109 cases needed (the word lists alone: 95) at the same median 33 tools.
THRESHOLD = 0.725
TIMEOUT = 1.0  # seconds
CHUNK = 100  # texts per embedding request
STICKY_REPLIES = 3
REMEMBERED = 200  # recent message vectors kept in memory (never stored): the person's last
# two messages go with each new one, and the free tier counts every text as a request
CLAUSE = re.compile(r"[.?!;,\n]+")


class ModelChanged(Exception):
    """The examples came back from a different model than the message (a fallback)."""


class EmbeddingRouter:
    def __init__(
        self,
        embedder: Embedder,
        cache: VectorCache,
        examples: Mapping[str, Sequence[str]] = GROUP_EXAMPLES,
        *,
        threshold: float = THRESHOLD,
        timeout: float = TIMEOUT,
    ) -> None:
        self.embedder = embedder
        self.cache = cache
        self.examples = {group: tuple(texts) for group, texts in examples.items()}
        self.threshold = threshold
        self.timeout = timeout
        self._vectors: dict[str, dict[str, tuple[Vector, ...]]] = {}  # model: group: vectors
        self._locks: dict[str, asyncio.Lock] = {}
        self._running: set[asyncio.Task[set[str]]] = set()
        self._model = ""  # the model the last message was embedded with
        self._recent: dict[tuple[str, str], Vector] = {}  # (model, text): vector

    async def choose(self, member_id: int, texts: Sequence[str]) -> set[str]:
        """The groups these texts are close to, or none if that can't be known in time."""
        task = asyncio.ensure_future(self._choose(member_id, texts))
        self._running.add(task)
        task.add_done_callback(self._finished)
        timer = asyncio.ensure_future(clock.sleep(self.timeout))
        try:
            done, _ = await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            timer.cancel()
        if task not in done:
            log.info("Embedding routing took over %ss; the word lists decide", self.timeout)
            return set()
        if task.cancelled() or task.exception() is not None:
            return set()
        return task.result()

    async def scores(self, member_id: int, texts: Sequence[str]) -> dict[str, float]:
        """Each group's best similarity to any of the texts or their clauses (for choosing
        a threshold too)."""
        model, vectors = await self._embed(member_id, pieces(texts))
        examples = await self._examples(member_id, model)
        return {
            group: max(similarity(v, e) for v in vectors for e in ex) if vectors else 0.0
            for group, ex in examples.items()
        }

    async def _embed(self, member_id: int, texts: list[str]) -> tuple[str, list[Vector]]:
        """The texts' unit vectors, embedding only those not seen lately with this model."""
        model = self._model
        known = {t: self._recent[(model, t)] for t in texts if (model, t) in self._recent}
        rest = [t for t in texts if t not in known]
        if rest:
            got = await self.embedder.embed(member_id, rest)
            if known and got.model != model:  # a fallback model: start again with it
                known, rest = {}, texts
                got = await self.embedder.embed(member_id, rest)
            model = self._model = got.model
            for text, vector in zip(rest, got.vectors, strict=True):
                known[text] = self._recent[(model, text)] = unit(vector)
            while len(self._recent) > REMEMBERED:
                del self._recent[next(iter(self._recent))]
        return model, [known[t] for t in texts]

    async def _choose(self, member_id: int, texts: Sequence[str]) -> set[str]:
        scored = await self.scores(member_id, texts)
        return {group for group, score in scored.items() if score >= self.threshold}

    async def _examples(self, member_id: int, model: str) -> dict[str, tuple[Vector, ...]]:
        if model in self._vectors:
            return self._vectors[model]
        async with self._locks.setdefault(model, asyncio.Lock()):
            if model in self._vectors:
                return self._vectors[model]
            texts = [t for examples in self.examples.values() for t in examples]
            have = self.cache.get(model, texts)
            missing = [t for t in dict.fromkeys(texts) if t not in have]
            for start in range(0, len(missing), CHUNK):
                chunk = missing[start : start + CHUNK]
                got = await self.embedder.embed(member_id, chunk)
                if got.model != model:
                    raise ModelChanged(f"examples came from {got.model}, the message from {model}")
                self.cache.put(model, chunk, got.vectors)
                have.update(zip(chunk, (unit(v) for v in got.vectors), strict=True))
            vectors = {g: tuple(have[t] for t in ex) for g, ex in self.examples.items()}
            self._vectors[model] = vectors
            return vectors

    def _finished(self, task: asyncio.Task[set[str]]) -> None:
        self._running.discard(task)
        if not task.cancelled() and (exc := task.exception()) is not None:
            log.info(
                "Embedding routing failed (%s: %s); the word lists decide", type(exc).__name__, exc
            )


def pieces(texts: Sequence[str]) -> list[str]:
    """The texts, and the clauses of any that have more than one, without repeats."""
    out = [t.strip() for t in texts if t.strip()]
    for text in texts:
        clauses = [c.strip() for c in CLAUSE.split(text) if len(c.split()) >= 2]
        if len(clauses) > 1:
            out += clauses
    return list(dict.fromkeys(out))


def recent_groups(db: Database, member_id: int, replies: int = STICKY_REPLIES) -> set[str]:
    """The groups whose tools ran in this person's last few replies."""
    rows = db.query(
        "SELECT DISTINCT t.name FROM reply_tools t WHERE t.reply_id IN "
        "(SELECT id FROM replies WHERE member_id = ? ORDER BY id DESC LIMIT ?)",
        (member_id, replies),
    )
    return {
        TOOL_GROUPS[r["name"]]
        for r in rows
        if r["name"] in TOOL_GROUPS and r["name"] != more_tools.spec.name
    }
