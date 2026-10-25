# AI behaviour evals

Each supported provider should still pick the right actions and keep replies
PDA-safe. These evals check that against real models. They're opt-in and never
part of `make test-all`.

```sh
GEMINI_API_KEY=... make evals                  # Gemini (the default; free tier is fine)
ANTHROPIC_API_KEY=... make evals PROVIDER=claude
THEMI_EVAL_OLLAMA_MODEL=qwen3:8b make evals PROVIDER=ollama
```

`providers.py` lists the environment variables for each provider. Use test
keys, never the family's own.

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
tier, `THEMI_EVAL_PACE` (6 seconds by default) spaces the cases out to stay
under the rate limit.

The plumbing has its own dry run in the default test run,
`tests/integration/test_eval_runner.py`. It uses the real Gemini adapter
against a fake Gemini over HTTP.
