"""P7b: choosing the embedding router's threshold, on P3's eval over P7a's cases.

    make evals EVAL_ARGS='-k thresholds -s'

Opt-in like the other evals: it embeds the group examples and every case's messages with
the test key (GEMINI_TEST_API_KEY), a few requests in all, and keeps the vectors in
`results/embeddings.db` so a second run makes none. It prints, at each threshold, recall
and the median tools sent for the word lists and embeddings together (as Themi runs
them), and for embeddings alone. Sticky groups aren't modelled: the cases have no
history beyond the message before.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from tests.evals.providers import EvalBackend
from tests.evals.routing import Routable, from_case, load_routing_cases, route_cases, totals
from tests.evals.scoring import load_cases
from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fakes.travel import FakeTravel
from tests.scenarios.harness import Scenario
from themi.ai.adapters.gemini import DEFAULT_EMBEDDING_MODEL, GeminiProvider
from themi.ai.embeddings import VectorCache, similarity
from themi.ai.errors import RetryableError
from themi.ai.types import Embeddings
from themi.core.routing import THRESHOLD, EmbeddingRouter, pieces
from themi.core.tools import GROUP_EXAMPLES, choose_groups
from themi.storage import open_database

CACHE = Path(__file__).parent / "results" / "embeddings.db"
PER_MINUTE = 90  # the free tier counts each text as a request: 100 a minute
THRESHOLDS = [round(0.5 + 0.025 * i, 3) for i in range(17)]  # 0.5 to 0.9


class CachedGemini:
    """Every text embedded once, ever: the cases' vectors are kept like the examples'."""

    def __init__(self, gemini: GeminiProvider, cache: VectorCache) -> None:
        self.gemini = gemini
        self.cache = cache

    async def embed(self, member_id: int, texts: Sequence[str]) -> Embeddings:
        model = self.gemini.model
        have = self.cache.get(model, texts)
        missing = [t for t in dict.fromkeys(texts) if t not in have]
        for start in range(0, len(missing), PER_MINUTE):
            chunk = missing[start : start + PER_MINUTE]
            got = None
            for attempt in range(6):
                try:
                    got = await self.gemini.embed(chunk)
                    break
                except RetryableError as exc:  # opt-in evals only: free-tier rate limits
                    if attempt == 5:
                        raise
                    await asyncio.sleep((exc.retry_after or 30) + 1)
            assert got is not None
            self.cache.put(model, chunk, got.vectors)
        have = self.cache.get(model, texts)
        return Embeddings(tuple(have[t] for t in texts), "gemini", model)


async def test_thresholds(
    scenario: Scenario,
    eval_backend: EvalBackend,
    fake_gmail: FakeGmail,
    fake_gcal: FakeGcal,
    fake_cozyla: FakeCozyla,
    fake_ourgroceries: FakeOurGroceries,
    fake_travel: FakeTravel,
) -> None:
    assert eval_backend.kind == "gemini" and eval_backend.api_key is not None
    CACHE.parent.mkdir(exist_ok=True)
    cache = VectorCache(open_database(CACHE))
    gemini = GeminiProvider(eval_backend.api_key, DEFAULT_EMBEDDING_MODEL, timeout=60)
    embedder = CachedGemini(gemini, cache)
    router = EmbeddingRouter(embedder, cache)
    cases: list[Routable] = [*map(from_case, load_cases()), *load_routing_cases()]
    every = [p for c in cases for p in pieces(c.texts)]
    await embedder.embed(0, every)  # all the cases' texts, in a few requests
    scores = {c.texts: await router.scores(0, c.texts) for c in cases}
    registry = scenario.app.services.tools

    def by_meaning(threshold: float) -> dict[tuple[str, ...], set[str]]:
        return {t: {g for g, s in got.items() if s >= threshold} for t, got in scores.items()}

    lines = [f"{'threshold':>9}  {'with word lists':>22}  {'embeddings alone':>22}"]
    words = totals(route_cases(registry, choose_groups, cases))
    lines.append(
        f"{'words':>9}  {f'{words.offered}/{words.needing}':>9} "
        f"{words.recall:>4.0%} {words.tools_sent:>5g} tools"
    )
    for threshold in THRESHOLDS:
        chosen = by_meaning(threshold)
        both = totals(
            route_cases(registry, lambda t, c=chosen: choose_groups(t) | c[tuple(t)], cases)
        )
        alone = totals(route_cases(registry, lambda t, c=chosen: c[tuple(t)], cases))
        lines.append(
            f"{threshold:>9}  {f'{both.offered}/{both.needing}':>9} {both.recall:>4.0%} "
            f"{both.tools_sent:>5g} tools  {f'{alone.offered}/{alone.needing}':>9} "
            f"{alone.recall:>4.0%} {alone.tools_sent:>5g} tools"
        )
    # How close each group's own examples sit to each other, for a sense of scale.
    vectors = cache.get(gemini.model, [e for ex in GROUP_EXAMPLES.values() for e in ex])
    for group, examples in GROUP_EXAMPLES.items():
        own = [similarity(vectors[a], vectors[b]) for a in examples for b in examples if a < b]
        lines.append(f"  {group:<10} examples alike: median {sorted(own)[len(own) // 2]:.2f}")
    chosen = by_meaning(THRESHOLD)
    both = route_cases(registry, lambda t: choose_groups(t) | chosen[tuple(t)], cases)
    lines += [
        f"  missed at {THRESHOLD}: {r.case.id}: {', '.join(r.missing)}"
        for r in both
        if not r.offered
    ]
    print("\n" + "\n".join(lines))
