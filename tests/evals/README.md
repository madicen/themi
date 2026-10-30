# AI behaviour evals

Each supported provider should still pick the right actions and keep replies
PDA-safe. These evals check that against real models. They're opt-in and never
part of `make test-all`.

```sh
GEMINI_TEST_API_KEY=... make evals             # Gemini (the default; free tier is fine)
ANTHROPIC_API_KEY=... make evals PROVIDER=claude
THEMI_EVAL_OLLAMA_MODEL=qwen3:8b make evals PROVIDER=ollama
```

`providers.py` lists the environment variables for each provider. Use test
keys, never the family's own. For Gemini the evals read only
`GEMINI_TEST_API_KEY` (from the environment or `.env`) and skip without it, so
the family's `GEMINI_API_KEY` in the same `.env` is never used.

## What a case checks

`cases.json` holds the cases. Each one is a message from Erin or her husband,
in a fresh household (the seeded family), with optional setup such as a
staged approval or a task. A case checks four things:

- **Tools.** Every tool in `expect` is called, nothing outside `expect` and
  `allow` is called, and nothing in `forbid` is called.
- **Arguments.** `args` checks the values: `lt`, `gt`, `equals` and `contains`,
  or `_json`, a list of words that must appear in the call's arguments.
- **Reply text.** `reply_must` and `reply_must_not` are regular expressions
  matched against the reply.
- **PDA safety, for every case.** No demand phrasing at the speaker's
  strictness, and nothing that looks like an energy score. Quoted `> ` lines
  are exempt.

Cases whose `requires` tools aren't built yet are skipped. The relay cases, for
example, wait for prompt 34.

## Output

Pass rates are printed by category, and the failing cases are listed with the
reason. A JSON copy goes to `results/`, which git ignores. For Gemini's free
tier, see the next paragraphs; `THEMI_EVAL_PACE` adds a fixed pause between cases if needed.

Cases that no model answered are counted separately as "couldn't run", not as
passes or failures. After three of those in a row the run stops, so it doesn't
burn through a quota that's already used up.

Free-tier quotas can be small, so each model's calls are capped per minute
(`THEMI_EVAL_RPM`, 10 by default), and a fallback model can share the load.
What we use, about 100 requests a full run:

    THEMI_EVAL_MODEL=gemini-3.5-flash-lite THEMI_EVAL_FALLBACK_MODEL=gemini-3.1-flash-lite \
      make evals

That takes 10 to 15 minutes. Please don't run it often: when prompts or models
change, and in the nightly job. One slice at a time works too:
`make evals EVAL_ARGS='-k energy'`. The limits for a key are listed at
<https://ai.dev/rate-limit>.

The plumbing has its own dry run in the default test run,
`tests/integration/test_eval_runner.py`. It uses the real Gemini adapter
against a fake Gemini over HTTP.

## Comparing two setups (P5)

One run can't tell a real change from noise. To compare, repeat each case and
time it:

```sh
make evals EVAL_ARGS='--repeat 3'                   # the tool groups (today)
make evals EVAL_ARGS='--repeat 3 --routing all'     # every tool on every call
.venv/bin/python -m tests.evals.compare tests/evals/results/gemini-groups-....json \
    tests/evals/results/gemini-all-....json
```

Each result keeps its run number, each model call's seconds (less any wait for
the per-minute pace) and the tools sent with the first call. The summary gives
the medians, and lists flaky cases (passed some runs) apart from failing ones.

`compare` scores both runs again with today's cases, lists the cases that always
passed in one and always failed in the other first (the real differences), and
gives a verdict under the rule agreed before the runs: the second wins if it
passes no fewer cases (give or take one), no case goes from always passing to
always failing, and it's at most 20% slower. `rescore` reads a saved run with
its repeats and timings too.

Three repeats of both setups is about 600 requests: on the free tier, run it in
the background, one setup at a time.

## The embedding router's threshold (P7b)

`test_router_thresholds.py` scores the word lists with embeddings added (as
`THEMI_TOOL_ROUTING=embeddings` runs them), and embeddings alone, on P3's eval
over the eval and routing cases, at thresholds from 0.5 to 0.9:

```sh
make evals EVAL_ARGS='-k thresholds -s'
```

It embeds with `GEMINI_TEST_API_KEY` and keeps the vectors in
`results/embeddings.db`, so only new or changed texts are embedded again. The
free tier counts each text as a request (100 a minute), so a first run waits
out the limit once or twice.
