"""P8b: which open task a message names, by meaning.

The model picks a task for complete_task (or cancel_task, reschedule_task), and the tool
checks that what they said names it: the model picks wrong ("We contacted Erin's parents"
marked the bins done). P8a's eval showed the word check gets this wrong both ways: it
refuses paraphrases ("jogged this morning" for "Go for a run") and lets one shared word
through ("Ran the dishwasher" for the run, "Cleaned the car" for every "Clean ..." task).

Here embeddings decide. What they said and each open task's title become vectors; a task
is named when it's the closest, at least `THRESHOLD` similar, and ahead of the next by
`MARGIN`. Being clearly the closest is what counts: absolute scores don't separate a near
miss from a paraphrase. Two word rules stay, where the single closest task can't be right:

- A short answer ("Yes please", "Done") that names nothing clearly itself is read as what
  it answers: Themi's last message, or their own message before it.
- "All", "both", "everything" mean several tasks. After a short answer, the tasks Themi's
  message listed by their titles; in a longer message, every task about as close as the best
  (within `GROUP_MARGIN`): "Both bathrooms are clean". "Broke down all the boxes" still
  names only the cardboard.

Nothing here ever holds up a "done": if embedding fails or takes over `TIMEOUT` seconds,
`TaskNamer.named` says it can't tell and the word check decides, as before P8b.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from themi import clock
from themi.ai.embeddings import Embedder, Vector, VectorCache, similarity, unit
from themi.core.events import words_in_common

log = logging.getLogger(__name__)

# From tests/evals/test_naming_thresholds.py on 2026-11-03 (P8b's Notes).
THRESHOLD = 0.6
MARGIN = 0.05
GROUP_MARGIN = 0.05
TIMEOUT = 1.0  # seconds
SHORT_ANSWER = 3  # words or fewer ("Yes please"): read with what Themi asked before it
ALL_OF_THEM = re.compile(r"\b(?:all|everything|every one|both)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Said:
    request: str  # their message
    previous: str = ""  # their message before it
    said_before: str = ""  # Themi's last message to them


def texts_to_score(said: Said, titles: Mapping[int, str]) -> list[str]:
    """Their message; and, for a short answer, what it answers."""
    request = said.request.strip()
    texts = [request] if request else []
    if len(request.split()) <= SHORT_ANSWER:
        texts += [t.strip() for t in (said.said_before, said.previous) if t.strip()]
    return list(dict.fromkeys(texts))


def which(
    said: Said,
    titles: Mapping[int, str],
    sims: Mapping[str, Mapping[int, float]],
    *,
    threshold: float = THRESHOLD,
    margin: float = MARGIN,
    group_margin: float = GROUP_MARGIN,
) -> frozenset[int]:
    """The tasks what they said clearly names (none: it names none clearly). `sims` holds,
    for each of `texts_to_score`, each task's similarity to it."""
    request = said.request.strip()
    every = bool(ALL_OF_THEM.search(request))
    own_words = len(request.split()) > SHORT_ANSWER or any(
        words_in_common(request, t) for t in titles.values()
    )
    for text in texts_to_score(said, titles):
        if every and text != request:  # "All done!" to a list of them, by their titles
            return frozenset(i for i, title in titles.items() if title.lower() in text.lower())
        if every and own_words:  # "Both bathrooms are clean"
            return around_best(sims[text], threshold, group_margin)
        if every:
            continue
        best = clear_best(sims[text], threshold, margin)
        if best is not None:
            return frozenset({best})
    return frozenset()


def clear_best(scores: Mapping[int, float], threshold: float, margin: float) -> int | None:
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    if not ranked or ranked[0][1] < threshold:
        return None
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < margin:
        return None
    return ranked[0][0]


def around_best(scores: Mapping[int, float], threshold: float, within: float) -> frozenset[int]:
    best = max(scores.values(), default=0.0)
    if best < threshold:
        return frozenset()
    return frozenset(i for i, score in scores.items() if score >= best - within)


class TaskNamer:
    def __init__(
        self,
        embedder: Embedder,
        cache: VectorCache,
        *,
        threshold: float = THRESHOLD,
        margin: float = MARGIN,
        group_margin: float = GROUP_MARGIN,
        timeout: float = TIMEOUT,
    ) -> None:
        self.embedder = embedder
        self.cache = cache
        self.threshold = threshold
        self.margin = margin
        self.group_margin = group_margin
        self.timeout = timeout
        self._running: set[asyncio.Task[dict[str, dict[int, float]] | None]] = set()

    async def named(
        self, member_id: int, said: Said, titles: Mapping[int, str]
    ) -> frozenset[int] | None:
        """The open tasks they named, or None if that can't be known in time."""
        if not titles:
            return frozenset()
        task = asyncio.ensure_future(self.scores(member_id, texts_to_score(said, titles), titles))
        self._running.add(task)
        task.add_done_callback(self._finished)
        timer = asyncio.ensure_future(clock.sleep(self.timeout))
        try:
            done, _ = await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            timer.cancel()
        if task not in done:
            log.info("Naming a task took over %ss; the word check decides", self.timeout)
            return None
        if task.cancelled() or task.exception() is not None or task.result() is None:
            return None
        sims = task.result()
        assert sims is not None
        return which(
            said,
            titles,
            sims,
            threshold=self.threshold,
            margin=self.margin,
            group_margin=self.group_margin,
        )

    async def scores(
        self, member_id: int, texts: Sequence[str], titles: Mapping[int, str]
    ) -> dict[str, dict[int, float]] | None:
        """Each text's similarity to each title. The titles' vectors are cached; None if
        the titles would come from a different model than the texts (a fallback)."""
        if not texts:
            return {}
        got = await self.embedder.embed(member_id, texts)
        model = got.model
        said = [unit(v) for v in got.vectors]
        wanted = list(dict.fromkeys(titles.values()))
        have: dict[str, Vector] = self.cache.get(model, wanted)
        missing = [t for t in wanted if t not in have]
        if missing:
            more = await self.embedder.embed(member_id, missing)
            if more.model != model:
                return None
            self.cache.put(model, missing, more.vectors)
            have.update(zip(missing, (unit(v) for v in more.vectors), strict=True))
        return {
            text: {i: similarity(vector, have[title]) for i, title in titles.items()}
            for text, vector in zip(texts, said, strict=True)
        }

    def _finished(self, task: asyncio.Task[dict[str, dict[int, float]] | None]) -> None:
        self._running.discard(task)
        if not task.cancelled() and (exc := task.exception()) is not None:
            log.info(
                "Naming a task failed (%s: %s); the word check decides", type(exc).__name__, exc
            )
