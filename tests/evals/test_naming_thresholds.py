"""P8b: choosing the "which task?" check's threshold and margins, on P8a's naming cases.

    make evals EVAL_ARGS='-k naming_thresholds -s'

Opt-in like the other evals: it embeds every case's scored text and the task titles with
the test key (GEMINI_TEST_API_KEY), and keeps the vectors in `results/embeddings.db` (as
the router thresholds do), so a second run makes no requests. It prints the word check,
then P8b's check at each setting: cases right, wrongly refused, wrongly accepted. The
shipped setting may let through only the one near miss no setting refuses.
"""

from __future__ import annotations

from tests.evals.naming import (
    format_naming,
    load_naming_cases,
    meaning_check,
    score,
    texts_needed,
    totals,
    word_check,
)
from tests.evals.providers import EvalBackend
from tests.evals.test_router_thresholds import CACHE, CachedGemini
from themi.ai.adapters.gemini import DEFAULT_EMBEDDING_MODEL, GeminiProvider
from themi.ai.embeddings import VectorCache, similarity
from themi.core.which_task import GROUP_MARGIN, MARGIN, THRESHOLD
from themi.storage import open_database

THRESHOLDS = (0.5, 0.55, 0.6, 0.65, 0.7)
MARGINS = (0.0, 0.02, 0.04, 0.05, 0.06, 0.08)
GROUP_MARGINS = (0.02, 0.05, 0.08)


async def test_naming_thresholds(eval_backend: EvalBackend) -> None:
    assert eval_backend.kind == "gemini" and eval_backend.api_key is not None
    CACHE.parent.mkdir(exist_ok=True)
    cache = VectorCache(open_database(CACHE))
    gemini = GeminiProvider(eval_backend.api_key, DEFAULT_EMBEDDING_MODEL, timeout=60)
    embedder = CachedGemini(gemini, cache)
    cases, drafts = load_naming_cases(), load_naming_cases(drafts=True)
    texts = texts_needed([*cases, *drafts])
    got = await embedder.embed(0, texts)
    vectors = dict(zip(texts, got.vectors, strict=True))
    titles = {t for c in [*cases, *drafts] for t in c.tasks}
    sims = {a: {b: similarity(vectors[a], vectors[b]) for b in titles} for a in texts}

    print(f"\nword check: {totals(score(cases, word_check))}")
    print("threshold margin group -> right, wrongly refused, wrongly accepted")
    for threshold in THRESHOLDS:
        for margin in MARGINS:
            for group in GROUP_MARGINS:
                check = meaning_check(sims, threshold=threshold, margin=margin, group_margin=group)
                t = totals(score(cases, check))
                print(
                    f"  {threshold:.2f} {margin:.2f} {group:.2f} -> "
                    f"{t.right:>2} {t.wrongly_refused:>2} {t.wrongly_accepted:>2}"
                )
    shipped = score(cases, meaning_check(sims))
    print(f"\nshipped ({THRESHOLD}, {MARGIN}, {GROUP_MARGIN}):\n{format_naming(shipped)}")
    if drafts:
        table = format_naming(score(drafts, meaning_check(sims)))
        print(f"\nnot reviewed yet (they don't count):\n{table}")
    # No setting accepts nothing: water and green tea are both drinks (P8b's Notes).
    assert {s.case.id for s in shipped if s.wrongly_accepted} <= {"water-not-tea"}
