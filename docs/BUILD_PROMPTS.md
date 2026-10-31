# Themi build prompts

Ordered prompts for building Themi. Work through them one at a time: say
**"implement the next prompt"** and Claude picks the first one whose status is `[ ]`.

- Design source of truth: [Themi Build Plan (V1)](https://claude.ai/artifact/PWX3iYKmbKy1UmCQrVF2Z1).
  Each prompt lists the plan sections to read first.
- Workflow rules live in [CLAUDE.md](../CLAUDE.md).
- Status: `[ ]` not started · `[~]` in progress · `[x]` done. When a prompt is done,
  add the date and a few lines under **Notes**: deviations from the plan, follow-ups,
  anything the next prompt needs to know.
- A prompt that turns out too big gets split into `NNa` / `NNb` here before work starts.

## Progress

| # | Prompt | Milestone | Status |
| --- | --- | --- | --- |
| 01 | Repository bootstrap and test harness | 1 Foundation | [x] |
| 02 | Settings, storage, migrations, encryption | 1 Foundation | [x] |
| 03 | Family and member data model | 1 Foundation | [x] |
| 04 | AI layer: interface, scripted provider, retry policy | 1 Foundation | [x] |
| 05 | AI layer: Claude, Gemini, OpenAI-compatible adapters | 1 Foundation | [x] |
| 06 | AI layer: per-person routing, fallback, breaker, JSON mode | 1 Foundation | [x] |
| 07 | Telegram channel | 1 Foundation | [x] |
| 08 | Outbox and PDA shield | 1 Foundation | [x] |
| 09 | Agent core and scenario harness | 1 Foundation | [x] |
| 10 | Process runtime, scheduler, Docker | 1 Foundation | [x] |
| 11 | Trust tiers engine | 2 Trust and memory | [x] |
| 12 | Approvals in Telegram | 2 Trust and memory | [x] |
| 13 | Rules: drafts and locking | 2 Trust and memory | [x] |
| 14 | Memory and context repair | 2 Trust and memory | [x] |
| 15 | Website v1: sign-in, dashboard, personal settings | 2 Trust and memory | [x] |
| 16 | Website v1: admin, tiers, rules, AI backend pages | 2 Trust and memory | [x] |
| 17 | Chat commands: /pause, /tracking, /site | 2 Trust and memory | [x] |
| 18 | Energy signals and capacity model | 3 Shadow Calendar | [x] |
| 19 | Good windows and outcome learning | 3 Shadow Calendar | [x] |
| 20 | Tasks, matching, habit reserve | 3 Shadow Calendar | [x] |
| 21 | Google sign-in and account linking | 4 Gmail and pantry | [x] |
| 22 | Gmail connector and polling | 4 Gmail and pantry | [x] |
| 23 | Email triage | 4 Gmail and pantry | [x] |
| 24 | Expected emails and anomaly detection | 4 Gmail and pantry | [x] |
| 25 | Pantry and grocery list (OurGroceries) | 4 Gmail and pantry | [x] |
| 26 | Google Calendar for Cozyla | 4 Gmail and pantry | [x] |
| 27 | Meal suggestions and vendor call scripts | 4 Gmail and pantry | [x] |
| 28 | Evals, live smoke tests, coverage gates | 4 Gmail and pantry | [x] |
| 29 | Backups and cloud deployment (Phase 2 gate) | 4 Gmail and pantry | [~] |
| D1 | Local dev run and Telegram simulator | Dev tooling | [x] |
| D2 | Simulator: copy a test session | Dev tooling | [x] |
| F1 | Feedback from chat: /bug and /idea | Feedback | [x] |
| F2 | Personal rules | Feedback | [x] |
| F3 | Busy times | Feedback | [x] |
| F4 | Tasks someone takes on stay theirs | Feedback | [x] |
| F5 | Asked-for actions, honest replies, check-in wording | Feedback | [x] |
| F6a | Chores: steps on tasks | Feedback | [x] |
| F6b | Chores: repeating schedules and escalation | Feedback | [x] |
| F7 | Chores: anchored schedules, deadlines, read-back | Feedback | [x] |
| S1 | Shadow Calendar: energy remarks recorded | Shadow Calendar review | [x] |
| S2 | Shadow Calendar: calendar, task load and busy times as inputs | Shadow Calendar review | [x] |
| S3 | Shadow Calendar: a private "how Themi sees my week" view | Shadow Calendar review | [x] |
| S4 | Energy-aware chore levels | Shadow Calendar review | [x] |
| G1 | Two-way grocery sync with OurGroceries | Groceries | [x] |
| F8 | Feedback fixes: nudge labels, check-ins, duplicate sends | Feedback | [x] |
| F9a | Exercise schedules: either-day rounds, rest days, a missed day moves to the next | Feedback | [x] |
| F9b | Exercise schedules: sunset-relative times | Feedback | [x] |
| F9c | Exercise schedules: distance plans | Feedback | [x] |
| L1a | Lists on demand: Themi's own lists | Lists | [x] |
| L1b | Lists on demand: the wall's lists | Lists | [x] |
| L2a | A "things to buy" list sorted by store | Lists | [x] |
| L2b | Things to buy in the carts | Lists | [ ] |
| H1 | Dishwasher: notice when the household is falling behind | Devices, early | [x] |
| F11 | Feedback: put off until a time, summaries, finding events, routine items | Feedback | [x] |
| F12 | Feedback: heads-ups explained, "one of us", emoji on the wall | Feedback | [x] |
| F13 | Feedback: problems talked through, mentions, nicknames, slow replies | Feedback | [x] |
| E1 | Email: suggest important senders | Feedback | [x] |
| S5 | Shadow Calendar: learning from reactions | Feedback | [x] |
| M1 | Memory: a record of conversations | Feedback | [x] |
| P1 | Faster replies: only the tools a message needs | Feedback | [x] |
| F14a | Feedback: one card per event, nudges at a time, check-ins kept in Themi, whose day | Feedback | [x] |
| F14b | Feedback: routine order, email setup, spending isn't shopping, passing messages on | Feedback | [x] |
| X1 | Spending: takeout and business expenses | Feedback | [x] |
| B1 | Breaks: a rest mode that ends with a question | Feedback | [x] |
| T1 | Tasks: urgent and important | Feedback | [x] |
| F15a | Feedback: changing a task's time, one task not two, reminders not events | Feedback | [x] |
| F15b | Feedback: summaries and cards on time, one morning message | Feedback | [x] |
| F15c | Feedback: the urgent email that shouldn't need a rule | Feedback | [x] |
| Rx1 | Medicines: safe reminders and advice | Feedback | [x] |
| E2 | Email: an audit instead of single questions | Feedback | [x] |
| E2b | Email audit: off the wall, and sliding scales | Feedback | [x] |
| P2a | Response timing, and a word while a reply is slow | Feedback | [x] |
| P2b | Faster replies, from the numbers | Feedback | [ ] |
| P3 | Router metrics: how well the tool groups are chosen | Feedback | [x] |
| P4 | Wrong actions: marked in chat, labelled in review | Feedback | [x] |
| P5 | Evals that can compare: repeats, timings, and every tool vs groups | Feedback | [x] 2026-10-30 |
| P6 | Near-twin tools: sent together, told apart, tested both ways | Feedback | [x] 2026-10-30 |
| P7a | Routing data: the family's kinds of message, labelled | Feedback | [x] 2026-10-30 |
| P7b | An embedding router, if P5 says routing stays | Feedback | [x] 2026-10-30 |
| F16a | Feedback: automatic is per person | Feedback | [x] |
| F16b | Feedback: noise emails in one message, inside the limit | Feedback | [x] |
| F16c | Feedback: time-sensitive, explaining email levels, the run, slow notices | Feedback | [x] |
| F16d | Feedback: only Gmail's Primary inbox counts | Feedback | [x] |
| F17a | Feedback: noise to archive in chat, the audit's subject and link, tasks by name | Feedback | [x] |
| F17b | Feedback: which list, and a reminder after a task is done | Feedback | [x] |
| F18a | Feedback: the wrong event moved, honest staging, a task for the other partner, "too tired" | Feedback | [x] |
| F18b | Feedback: routines asked about, the slow note after a card, noise in chat again | Feedback | [x] |
| F18c | Feedback: button rows, the wall's to-do order, emails dealt with in Gmail, whose habit offer | Feedback | [x] |
| F18d | Feedback: the wall's to-do list in order | Feedback | [x] |
| F18e | Feedback: the chore sync stuck, the wrong task changed, reminders that aren't tasks | Feedback | [x] |
| F18f | Feedback: a wrong year, the summary twice, a task already open, stale cards, the heads-up late | Feedback | [x] |
| F18g | Feedback: "no" closed eight tasks, a title that says "today" | Feedback | [x] |
| F18h | Feedback: replies that say who has a task truly, routine checks with a skip | Feedback | [x] |
| F19a | Feedback: a snooze to tomorrow, yesterday's summary, a stale end-of-day list, quotes, an event already added | Feedback | [x] |
| F19b | Idea: a word when a task is done | Feedback | [x] |
| F19c | Idea: a shared task put off by one person stays with the other | Feedback | [x] |
| O1 | Idea: when it's too much, a few things now and the rest spread out | Feedback | [ ] |
| R1a | Routines kept in Themi: routines, items and checks, from chat | Feedback | [x] |
| R1b | Routines kept in Themi: the wall, both ways | Feedback | [x] |
| K1 | Calendars: read your own, privately | Calendars | [x] |
| K2 | Calendars: a summary of the day | Calendars | [x] |
| K3 | Calendars: creating and changing events | Calendars | [x] |
| K4 | Calendars: travel time and "time to get ready" | Calendars | [x] |
| K4b | Calendars: drive time on request | Calendars | [x] |
| K5 | Calendars: blocking time for tasks | Calendars | [x] |
| C1a | Cozyla: unofficial client and a read-only check | Cozyla | [x] |
| C1b | Cozyla: two-way to-do list sync (trial) | Cozyla | [x] |
| C1c | Cozyla: every list, reassigning, the family member, named lists | Cozyla | [x] |
| C2a | Cozyla: chore and routine client, schedules both ways | Cozyla | [x] |
| C2b | Cozyla: Themi's chores on the chore chart, Themi in charge | Cozyla | [x] |
| C2c | Reminders by importance: end of day, more specific when overdue | Cozyla | [x] |
| C3 | Cozyla: routines, and morning and evening routine checks | Cozyla | [x] |
| F10 | Feedback: due times, one nudge at a time, plain phrasing, check-in reviews | Feedback | [x] |
| C2d | Cozyla: one chore on the chart at a time | Cozyla | [x] |
| 30 | LG ThinQ connector | 5 Devices | [ ] |
| 31 | Laundry module and rescue protocol | 5 Devices | [ ] |
| 32 | SmartLife / Tuya feeders | 5 Devices | [ ] |
| 33 | Seasonal and long-term maintenance | 5 Devices | [ ] |
| 34 | Liaison: relays, family group, alignment prompts | 6 Liaison and food | [ ] |
| 35 | Meal reminders, takeout rescue, cart staging | 6 Liaison and food | [ ] |
| 36 | Research: CatGenie, automated calls, SMS | 7 Research | [ ] |
| R2 | Research: Google Home | 7 Research | [x] |
| GT1a | Google Tasks as an inbox: voice-added items processed, then removed | Google Home | [x] |
| GT1b | Themi's tasks on Google Tasks, kept apart from the inbox | Google Home | [x] |
| GK1 | Groceries said to Google Home, from Google Keep | Google Home | [x] 2026-10-30 |
| GK2 | Themi's grocery list shown in Keep, both ways | Google Home | [x] 2026-10-30 |

## Fixed technical choices

Decided up front so prompts don't re-litigate them. Change one only with the user's agreement,
and record the change here.

- Python 3.12+ (Docker image `python:3.13-slim`), package `themi` under `src/themi`.
- FastAPI + uvicorn for HTTP; Jinja2 templates + HTMX (vendored, no CDN) for the website.
- `python-telegram-bot` (v21+, async) in long-polling mode.
- AI SDKs: `anthropic` (Claude), `google-genai` (Gemini), `openai` (Ollama, LM Studio and any
  other OpenAI-compatible server via `base_url`).
- Own REST clients over `httpx` for Google (OAuth, Gmail, Calendar) and Tuya, so they are easy
  to point at local HTTP fakes.
- SQLite (stdlib `sqlite3`, WAL, FTS5) with a small numbered-migration runner. No ORM.
- `cryptography` Fernet for secrets at rest; key from `THEMI_SECRET_KEY` or a key file.
- Tests: pytest, pytest-asyncio, Hypothesis, coverage.py. Lint/format: ruff. Types: pyright.
- Version control: jj (colocated with git). Each major change is its own `jj commit`.
- One process runs the bot, scheduler and website on one asyncio loop.
- The default AI backend is Gemini's free tier on `gemini-3.5-flash-lite` for every task.
  Changed from prompt 05's `gemini-3.8-flash` with the user's agreement on 2026-10-25: that
  model allowed 20 free requests a day, and flash-lite scored well in prompt 28's evals. The
  plan named no Gemini model before; its provider table now lists flash-lite.

---

## Milestone 1: Foundation

### 01 · Repository bootstrap and test harness
Status: [x] (2026-10-24)
Depends on: none
Read first: plan sections "Testing", "Architecture" (code package table).

Build:
- Remove the early `src/hema/` scaffolding and the old `.venv`. Salvage ideas from
  `hema/clock.py` and `hema/db.py` if useful, but the package is now `themi`.
- Version control already exists (a colocated jj repo whose first commit holds `CLAUDE.md` and
  `docs/`). Commit the bootstrap as the next change.
- `pyproject.toml` for `themi` (setuptools, `src/` layout, `themi` console script). Runtime
  deps are added by later prompts as they're needed. Dev deps: pytest, pytest-asyncio,
  hypothesis, coverage, ruff, pyright.
- `src/themi/__init__.py`, `src/themi/clock.py`: `now()`, `freeze(at)`, `advance(delta)`, all
  timezone-aware. Nothing else in the codebase may call `datetime.now()` or `time.time()` for
  business logic. Add a ruff/grep check that enforces this.
- Test layout: `tests/unit`, `tests/integration`, `tests/scenarios`, `tests/live`,
  `tests/evals`, `tests/fakes`, `tests/fixtures`, plus a root `conftest.py` that registers
  pytest markers (`integration`, `scenario`, `live`, `eval`). Live and eval tests are skipped
  unless explicitly selected.
- `Makefile`: `install`, `fmt`, `lint` (ruff + pyright), `test` (unit only), `test-all`
  (unit + integration + scenarios), `test-live`, `evals`, `cov` (coverage report).
- `.github/workflows/ci.yml`: on push and PR, run lint, type check and `make test-all` on
  Python 3.12 and 3.13.
- `.gitignore`, `.env.example` (just `THEMI_SECRET_KEY` and `THEMI_DB_PATH` for now),
  `README.md` with a one-paragraph description, a link to the plan, and dev setup steps.

Tests:
- Clock: freeze, advance, timezone awareness, and a check that `freeze` rejects naive datetimes.
- A test proving the "no direct now()" check catches a violation.

Done when: `make lint`, `make test` and `make test-all` pass locally, CI config is valid YAML,
and the bootstrap is committed with jj.

Notes:
- Every `tests/` layer folder is a package (`__init__.py`), so test files with the same name can
  exist in different layers. The conftest applies each layer's marker from its folder. A layer
  with no tests yet doesn't fail the run.
- `frozen_clock` fixture: Wed 2026-10-21 16:00 UTC (09:00 Pacific). The clock unfreezes
  automatically after every test. `clock.advance()` needs a frozen clock and refuses negative
  deltas.
- `make lint` also runs `tools/check_clock.py`. `time.monotonic()` stays allowed for durations.
- pyright is pointed at the Makefile's interpreter (`--pythonpath`), so it works with `.venv`
  locally and system Python in CI.
- CI hasn't run on GitHub yet (no remote). The workflow is valid YAML and mirrors the local
  `make` targets.

### 02 · Settings, storage, migrations, encryption
Status: [x] (2026-10-24)
Depends on: 01
Read first: "Accounts and data model" (storage bullet), "Security and privacy" (secrets at rest),
"Deployment and hosting" (backups and updates).

Build:
- `themi.settings`: pydantic model loaded from environment and an optional `.env`
  (`THEMI_DB_PATH`, `THEMI_SECRET_KEY` or `THEMI_SECRET_KEY_FILE`, `THEMI_PUBLIC_URL`,
  `TELEGRAM_BOT_TOKEN`, log level). Fail fast with a clear message on missing required values.
- `themi.storage.db`: a thread-safe SQLite wrapper (WAL, foreign keys on, one connection, one
  lock) with `execute`, `query`, `one`, `transaction()` context manager.
- `themi.storage.migrations`: numbered `.sql` files under `src/themi/storage/migrations/`, a
  `schema_version` table, apply-on-startup, refuse to start if the DB is newer than the code.
- `themi.storage.secrets`: Fernet encrypt/decrypt helpers plus a `SecretStr`-style wrapper whose
  `repr` and `str` never reveal the value. Provide a `themi keygen` CLI subcommand.
- Logging setup with a redaction filter that masks anything that looks like a key or token.

Tests:
- Migrations apply in order, are idempotent, and a too-new DB is refused.
- Transactions roll back on exception.
- Encryption round-trips, a wrong key fails loudly, and `repr` of a secret is masked.
- The log redaction filter masks sample tokens (Telegram, Anthropic, Google, Gemini formats).
- Integration: write an encrypted secret, then scan the raw DB file bytes and confirm the
  plaintext is absent.

Done when: all tests pass and the storage layer is committed.

Notes:
- Migration SQL files live in `src/themi/storage/schema/` rather than `migrations/`, so they
  don't share a name with the `themi.storage.migrations` module. New migrations are
  `000N_name.sql` there, numbered with no gaps.
- `themi.storage.open_database(path)` opens the database and migrates it. Use it everywhere.
  Migration 0001 creates `meta` (key/value) and `app_secrets` (household-level encrypted
  credentials, via `SecretStore`).
- `Secret.reveal()` is the only way to read a secret's value. Secrets can't be hashed or pickled.
- `TELEGRAM_BOT_TOKEN` is optional in `Settings` for now. Prompt 07 should require it when the
  bot starts. `Settings.load()` reads `.env` from the working directory, and real environment
  variables win.
- `themi.logs.configure_logging()` exists, but nothing calls it yet. `themi run` (prompt 10)
  should call it.
- Environment: a Homebrew upgrade (3.14 to 3.15) broke the venv mid-session. It's rebuilt on
  `make venv VENV_PYTHON=/home/linuxbrew/.linuxbrew/opt/python@3.15/bin/python3.15`. System
  Python 3.12 can't create venvs without `sudo apt install python3.12-venv`. CI still tests
  3.12 and 3.13; consider adding 3.15 to the matrix.

### 03 · Family and member data model
Status: [x] (2026-10-24)
Depends on: 02
Read first: "Accounts and data model", "How the family uses Themi" (management website bullets).

Build:
- Migration for `family` (single row), `members`, `linked_accounts`, `devices`, `invites`,
  `message_log`. Fields as in the plan's entity table. Member settings include quiet hours, the
  daily proactive-message limit, PDA shielding (on by default) and strength, recovery speed,
  tracking-input toggles, and role (admin or member).
- Repositories in `themi.accounts` (plain functions or small classes over the db wrapper) with
  typed dataclasses for each entity.
- Invites: an admin creates a one-time invite code tied to a new member; a member redeems it
  with `/start <code>` (wired up in prompt 07). Codes expire after 24 hours and work only once.
- First-run CLI: `themi init` prompts for the family name, timezone, monthly takeout budget and
  the first admin member, and prints an invite code for the admin's Telegram.
  `themi invite <name>` creates further members.
- Test fixtures in `tests/fixtures/family.py`: a seeded family (Erin as admin, her husband as
  member) with realistic settings, usable by every later test.

Tests:
- CRUD for each entity, role checks (only admins can create members), and invite expiry and
  single use.
- Deleting a member deletes their linked accounts, messages and settings.
- `themi init` end to end against a temp DB.

Done when: the fixtures exist and are used by tests, and everything is committed.

Notes:
- Everything goes through `themi.accounts.AccountStore(db, cipher)`. Changes take an `actor`:
  a `Member`, or `SYSTEM` for the CLI. Admin checks re-read the actor's role from the database,
  so a stale `Member` object can't keep rights it has lost.
- Rules enforced: admins manage members, roles, invites, devices and family settings. Members
  change only their own personal settings and linked accounts. The last admin can't be demoted
  or deleted.
- The family has no AI settings. The plan's per-member backend paragraph supersedes the
  entity table, so prompt 06 adds `member_ai_settings` instead.
- Invites: 8-character codes shown as `XXXX-XXXX`, without 0/O/1/I/L. Only a SHA-256 hash is
  stored. Codes are case- and spacing-tolerant, single-use and last 24 hours, and a new code
  replaces any unused one. A Telegram id can't be paired with two members.
- Gmail addresses are stored lowercase and are unique across the family. Refresh tokens and
  device credentials are encrypted.
- Money is stored as integer cents (`takeout_budget_cents`). Quiet hours are `HH:MM` in the
  family's timezone.
- Test fixtures: `store` (empty, migrated) and `family` (a `SeededFamily` with `.erin`,
  `.husband` and `.store`, both paired with Telegram ids 1001 and 1002) are available to every
  test through `pytest_plugins`. For harnesses, use `seed_family(make_store())`. The husband's
  fixture name is just "Husband".
- Added 2026-10-25: `themi init` and `themi invite` also print a tap-to-start link,
  `https://t.me/<bot>?start=<code>` (`setup.start_link`). The CLI looks up the bot's username
  with Telegram's `getMe` (`TELEGRAM_API_URL` is honoured, so tests use the fake). Without a
  token, or if Telegram can't be reached, the link is left out and the code prints as before.

### 04 · AI layer: interface, scripted provider, retry policy
Status: [x] (2026-10-24)
Depends on: 01
Read first: "AI backend" (all subsections), "Testing" → AI layer rows.

Build:
- `themi.ai.types`: provider-neutral message, tool definition (JSON Schema), tool call, tool
  result, and response types. Includes stop reasons (`end`, `tool_use`, `max_tokens`,
  `refusal`) and usage.
- `themi.ai.provider`: a `Provider` protocol with three operations: `chat(system, messages,
  tools, ...)`, `structured(system, prompt, schema, ...)` and `transcribe(audio, mime)`. Plus
  capability flags (`supports_tools`, `supports_audio`, `supports_structured`).
- `themi.ai.errors`: `RetryableError` (with optional `retry_after`), `PermanentError`
  (config/auth), `RefusalError`, `CapabilityError`.
- `themi.ai.retry`: one retry policy for all providers.
    - Retry on 429, 500, 502, 503, 504, 529, timeouts and connection errors. Never retry 400,
      401, 403 or 404.
    - Full jitter: `random(0, min(cap, base * 2**attempt))`, base 1 s, cap 60 s, and a
      `Retry-After` value wins.
    - Attempts: 3 for `interactive` calls and 6 for `background` calls.
    - The sleep function and the random source are injectable, so tests never actually sleep.
- `tests/fakes/scripted_provider.py`: a `ScriptedProvider` that returns queued responses
  (text, tool calls, errors), records every request, and can be told to fail N times with a
  given status.

Tests:
- Every retryable and non-retryable status. `Retry-After` precedence. Hypothesis property test:
  the delay is always within the jitter bounds. Attempt caps per call kind. Refusals are not
  retried.
- The scripted provider's own behaviour (queueing, recording, failure injection).

Done when: the AI interface is stable enough for adapters, and everything is committed.

Notes:
- The whole AI layer is async, because the Telegram bot and website run on asyncio.
- `Message.raw` and `raw_provider` carry a provider's native assistant turn. Adapters must replay
  `raw` unchanged when the same provider sees the conversation again, which matters for Claude's
  thinking blocks in tool loops, and must rebuild from neutral blocks otherwise. `raw` doesn't
  affect equality.
- All tool results for one assistant turn go back in a single `Message.tool_results(...)`.
- Retryable statuses are 408, 429, 500, 502, 503, 504 and 529. 408 was added as an HTTP
  timeout. Every other status is a `PermanentError`. Bare `TimeoutError` and `ConnectionError`
  are also retried.
- Addition to the plan: `RetryPolicy.max_wait` (20 s interactive, 300 s background). If
  `Retry-After` asks for longer, the policy gives up at once with `RetriesExhausted`, so the
  router (prompt 06) can move to the next provider instead of blocking someone for, say, a
  Gemini quota reset.
- `RetriesExhausted.last_error` keeps the final `RetryableError`, with its status and
  `retry_after`.
- `tests/fakes/scripted_provider.py`: `queue_text`, `queue_tool_call(s)`, `queue_structured`,
  `queue_transcription`, `queue_error`, `queue_refusal`, and `fail(n, status=, retry_after=,
  op=)`. Every call is recorded in `.requests`. An empty queue raises `AssertionError`.

### 05 · AI layer: Claude, Gemini, OpenAI-compatible adapters
Status: [x] (2026-10-24)
Depends on: 04
Read first: "AI backend" → Providers, Weaker local models. Before writing the Claude adapter,
load the `claude-api` skill and follow it (current model IDs, adaptive thinking, effort,
refusal fallbacks). Check the current `google-genai` and `openai` SDK docs too, rather than
going from memory.

Build:
- `themi.ai.adapters.anthropic`: official `anthropic` SDK with SDK retries disabled
  (`max_retries=0`), so only our policy retries. Default model `claude-opus-5-5`. Map tools to
  strict tool definitions, and map SDK exceptions onto our error types, including `Retry-After`.
  Enable server-side refusal fallback as the skill describes. Configurable `base_url` for tests.
- `themi.ai.adapters.gemini`: official `google-genai` SDK. Tools via function declarations,
  structured output via response schema, and audio input for transcription. Map quota errors
  (429 RESOURCE_EXHAUSTED) to `RetryableError`.
- `themi.ai.adapters.openai_compat`: official `openai` SDK with `base_url`. Presets for Ollama
  (`http://localhost:11434/v1`) and LM Studio (`http://localhost:1234/v1`). Capability flags
  are configurable per model, because local models vary.
- `tests/fakes/http_ai.py`: local HTTP fake servers (FastAPI under uvicorn on a random port)
  imitating the Anthropic Messages API, the Gemini API and an OpenAI-compatible
  chat-completions API closely enough for the SDKs. Each can be scripted to return tool calls,
  JSON, 429/503/529 with `Retry-After`, timeouts and malformed bodies.

Tests (integration, against the fakes over real HTTP):
- For each adapter: a plain reply, a tool call round trip, structured output, each error class
  mapped correctly, `Retry-After` surfaced, and confirmation that the SDK's own retries are off
  (exactly one HTTP request per attempt).
- Live smoke tests in `tests/live/` (skipped by default), one per provider, reading keys from env.

Done when: all three adapters pass against the fakes, and everything is committed.

Notes:
- SDK versions tested: anthropic 2.3.0, google-genai 2.33.0, openai 3.37.0.
- Claude:
    - Default `claude-opus-5-5` with `effort` sent explicitly (default `medium`). No sampling
      parameters, no `thinking` field (adaptive by default) and no forced `tool_choice`.
    - On Opus 5.5, Opus 5, Fable 5.1 and Sonnet 5.5 it adds `fallbacks: "default"` with beta
      `server-side-fallback-2026-07-01`.
    - Tools get `strict: true` only when the schema sets `additionalProperties: false`.
      Prompt 09 should write closed schemas for every tool.
    - SDK 2.x sends the key as `Authorization: Bearer`, not `x-api-key`, with
      `anthropic-version: 2026-10-21`.
- Gemini, checked against ai.google.dev on 2026-10-24:
    - The default chat model is `gemini-3.8-flash`, which has a free tier.
    - For transcription, `gemini-3.5-flash-lite` is explicitly priced for audio input and is
      the suggested default for the `transcription` task in prompt 06.
    - `gemini-4-argon` has no free tier. Gemini 2.0 is shut down.
    - The pricing page confirms free-tier content is used to improve Google's products.
- The google-genai SDK sends some fields in snake_case (`parameters_json_schema`, `mime_type`).
  Google's JSON parser accepts both, and the fake tests accept either.
- OpenAI-compatible: capabilities are per configuration (`supports_tools`, `supports_structured`,
  `supports_audio` on `AdapterConfig`). Tools on a model marked `tools=False` raise
  `CapabilityError` before any request is sent, which is the router's cue for JSON action mode.
- New `MalformedOutputError` covers non-JSON structured output, truncated structured output and
  unparseable tool arguments. The retry policy doesn't retry it. Prompt 06's JSON mode decides
  whether to retry once.
- `tests/fakes/http_ai.py` (`fake_ai` fixture) replies to any POST from a FIFO queue, so a test
  queues replies in the order of its calls. It returns 599 when nothing is queued. Builders:
  `anthropic_text`/`_tool_use`/`_error`, `gemini_text`/`_function_call`/`_error`,
  `openai_completion`/`_tool_call`/`_error`.
- Live tests (`make test-live`) need `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` and/or
  `THEMI_LIVE_OLLAMA_MODEL`. They haven't been run yet because no keys are available here.

### 06 · AI layer: per-person routing, fallback, breaker, JSON mode
Status: [x] (2026-10-24)
Depends on: 03, 05
Read first: "AI backend" → Routing per task, the per-member backend paragraph, Weaker local
models, Retries and backoff.

Build:
- Migration for `member_ai_settings`: per member, per task (`conversation`, `pda_rewrite`,
  `email_triage`, `structured_misc`, `transcription`), a primary provider config and an
  ordered fallback chain. API keys are stored encrypted. New members default to Gemini's
  free tier.
- `themi.ai.router`: `client_for(member_id, task)` returns a callable that applies the retry
  policy, then walks the fallback chain. Shared tasks use the owning member's backend. Keys are
  never shared across members.
- `themi.ai.breaker`: a per-(member, provider) circuit breaker. It opens after 5 consecutive
  failures, half-opens after 5 minutes (clock module) and is closed again by one successful probe.
- `themi.ai.json_mode`: for providers without tool support, ask for a JSON action list, then
  validate it against the same tool schemas. On failure, retry once with the validation error
  included, then return a plain reply with no actions.
- Background-call failures raise a typed `Deferred` result so the scheduler (prompt 10) can
  re-queue the work instead of dropping it.
- A `test_connection(member_id, task)` helper for the website's connection test button.

Tests:
- Key isolation: Erin's request never carries her husband's key, even through fallbacks.
- Fallback order, breaker transitions (with the frozen clock), JSON-mode success, retry and
  give-up paths, `Deferred` for background calls, and keys absent from logs and exceptions.

Done when: the router is the only way the rest of the code reaches a model, and everything is
committed.

Notes:
- Schema: two tables instead of one per task. `ai_backends` holds a provider a member sets up
  once, with its encrypted key. `ai_routes` holds an ordered list of backend ids per (member,
  task), with an optional model override. A key is entered once rather than per task.
  `AISettingsStore` is self-service only: not even admins can see or edit another member's AI
  settings.
- Defaults: `ensure_defaults()` runs lazily on first use. It gives the member a keyless
  "Gemini (free tier)" backend: `gemini-3.8-flash` for every task, `gemini-3.5-flash-lite` for
  transcription. Until a key is added, calls raise `AllProvidersFailed` with
  `needs_setup == True`. Prompts 09 and 16 should turn that into "add your Gemini key on the
  website".
- Usage: `router.client_for(member_id, AITask.X).chat/structured/transcribe(...)`, which accepts
  `on_retry=` (use it for Telegram's "typing" indicator). For shared tasks, the caller passes the
  owning member's id.
- Failure handling:
    - Interactive calls that fail everywhere raise `AllProvidersFailed`. Background calls raise
      `Deferred`, whose `.retry_after` is the largest provider hint, for the scheduler.
    - A refusal moves to the next backend, since a different model isn't a repeat as-is. If every
      backend refuses, the `RefusalError` itself is raised.
    - Permanent, capability and malformed-output errors skip to the next backend.
- The breaker counts each failed attempt, not each failed call, so 5 failures can open it in the
  middle of retries. Once open, the remaining attempts stop and the chain moves on.
- JSON mode turns on automatically when tools are passed to a backend with
  `supports_tools=False`. It needs `supports_structured`. Actions come back as normal
  `ToolCall`s with ids `json_N`, so the agent loop doesn't need to know which mode ran.
- `tests/unit/test_architecture.py` fails if anything outside `themi.ai` imports `anthropic`,
  `openai`, `google.genai` or `themi.ai.adapters`.

### 07 · Telegram channel
Status: [x] (2026-10-24)
Depends on: 03
Read first: "How the family uses Themi" → In Telegram, Chat commands; "Integrations" (Telegram
row); "Security and privacy" (who can talk to the bot).

Build:
- `themi.channels.telegram` using `python-telegram-bot` v21+ in long-polling mode, with a
  configurable `base_url` for tests.
- Member pairing: `/start <invite code>` links the Telegram user id to the member. All other
  updates from unknown user ids are ignored and logged (id only, no content).
- Inbound handling turns every text, voice note, button tap (callback query) and reaction
  (`message_reaction` updates) into an internal `InboundEvent` dataclass. These go to a handler
  interface that the agent core implements in prompt 09; for now an echo handler is enough.
- Voice notes: download the file and pass the bytes and MIME type along. Transcription is wired
  in prompt 09.
- Outbound primitives: send text with optional inline keyboard (2–3 buttons), edit message,
  show "typing" while a reply is being prepared, react to a message. Every send is recorded in
  `message_log` with the Telegram message id.
- Button callback data is a short opaque token mapped to a server-side record, so payloads are
  never trusted from the client.
- Resilience: reconnect with backoff after polling errors, and resume cleanly after a restart
  without reprocessing updates.
- `tests/fakes/telegram_api.py`: an HTTP fake of the Bot API endpoints used (getUpdates,
  sendMessage, editMessageText, sendChatAction, getFile, file download, setMessageReaction,
  answerCallbackQuery) with helpers to inject updates.

Tests:
- Integration against the fake: pairing, non-member ignored, text/voice/button/reaction become
  the right `InboundEvent`, outbound sends are logged, recovery from a polling error, and no
  duplicate processing after a restart.

Done when: a member can pair and get echoes back against the fake, and a manual run with a real
bot token works. Commit.

Notes:
- Not yet verified against real Telegram: there's no bot token here. To try it, set
  `TELEGRAM_BOT_TOKEN` in `.env`, run `themi init` (or `themi invite <name>`), start `themi bot`,
  and send `/start <code>` to the bot. It echoes back what you send.
- python-telegram-bot 22.8. Themi uses PTB's `Bot` with its own polling loop, not PTB's
  `Application`. The offset is stored in `meta` (`telegram.offset`) once each update is handled,
  so it's at-least-once with a tiny window. An update whose handler raises is logged and skipped.
- The channel sets `PTB_TIMEDELTA=1` (PTB's future default) before importing `telegram`.
  `_seconds()` accepts either form.
- Privacy fix found by the tests: PTB logs whole updates at DEBUG, and httpx logs URLs containing
  the bot token at INFO. `themi.logs.quiet_chatty_libraries()` caps telegram, httpx, httpx2,
  httpcore and hpack at WARNING. The channel and `configure_logging()` both call it.
- Pairing: `/start <code>`. Wrong codes get a generic reply, and after 5 in an hour that Telegram
  account is ignored (in memory). Already-paired members get "you're already connected".
- Buttons: `Button(label, kind, payload)`. Only a random token goes to Telegram; `kind` and
  `payload` live in `callback_tokens` (7-day TTL). A tap retires every button on that keyboard,
  and only the member the message was sent to can tap. The agent (prompt 09) and approvals
  (prompt 12) dispatch on `ButtonPress.kind`.
- Reactions: `ReactionTypeEmoji` only, reporting newly added emoji. Telegram's docs say reaction
  updates need `allowed_updates`, which is sent, and admin rights in groups. Check during the
  real-bot test that private-chat reactions arrive.
- Outbound: `send_text`, `edit_text`, `react`, and `async with channel.typing(member)`. Flood
  control (429 with retry_after) and network errors are retried up to 3 times. Prompt 08's outbox
  must be the only caller of `send_text` outside pairing.
- New dev dependency: python-multipart, which the fake needs to parse PTB's form posts. The
  website (prompt 15) will need it at runtime.
- `themi bot` runs the channel on its own in echo mode. Prompt 10 replaces it with `themi run`.

### 08 · Outbox and PDA shield
Status: [x] (2026-10-24)
Depends on: 06, 07
Read first: "Module behaviour" → A (PDA shielding); "How the family uses Themi" (quiet by
default); "Testing" → PDA shield and Outbox rows.

Build:
- `themi.channels.outbox`: the only path for sending anything to a person.
    - Priorities: `reply` (immediate, not counted against the limit), `urgent` (immediate,
      ignores quiet hours), `normal` and `low` (respect quiet hours and the daily
      proactive-message limit).
    - Deferred messages go to a queue table with `send_after`.
    - A dedupe key suppresses repeats.
    - A `ReceptivityProvider` hook decides "send now or wait for the next good window". Until
      prompt 19 it returns "now" outside quiet hours.
- `themi.channels.pda`:
    - A rule-based checker that flags demand phrasing: "you need to", "you have to", "you
      must", "don't forget", "remember to", "make sure", "right now", "immediately", "ASAP",
      and imperative verbs at the start of a sentence.
    - A per-member strictness level (0–3) chooses which rule sets apply.
    - Flagged text is rewritten through the `pda_rewrite` AI task (structured output: rewritten
      text, plus optional two-option buttons) and checked again before sending.
    - If the AI is unavailable or the rewrite still fails the check, a deterministic softener
      applies phrase substitutions.
- Calibration: feedback signals adjust that person's strictness within bounds. Signals are
  in-chat phrases ("too pushy" raises it, "just tell me" and "that was fine" lower it) and
  reactions on Themi's messages. Every change is logged.
- Corpora in `tests/fixtures/pda/`: `demanding.txt` (at least 60 lines) and `acceptable.txt`
  (at least 60 lines, including two-option choices and gentle suggestions).

Tests:
- Every line of `demanding.txt` is flagged at default strictness, and no line of
  `acceptable.txt` is.
- Rewrite path (scripted provider), re-check failure falls back to the softener, softener
  output passes the checker, and calibration moves strictness the right way and clamps at the
  bounds.
- Outbox: quiet-hours deferral and release, daily limit, urgent bypass, reply priority not
  counted, dedupe.

Done when: every outgoing message in the codebase goes through the outbox. Commit.

Notes:
- Usage: `Outbox(store, sender=channel, shield=PdaShield(AIRewriter(router)), receptivity)`,
  then `await outbox.send(member, text, priority=Priority.X, buttons=, kind=, dedupe_key=,
  deadline=)`. The scheduler (prompt 10) must call `await outbox.flush()` every minute or so.
- Deadline semantics, a refinement of the plan: once a deadline passes, the receptivity hook and
  the daily limit stop holding a message, but quiet hours still do. `urgent` is the only way
  through quiet hours. Urgent messages count toward the daily limit but are never held by it.
  A daily limit of 0 means only urgent messages and messages past a deadline get through.
- Shielding runs at delivery time, not at queue time. `outbox.text` keeps the original and
  `outbox.sent_text` records what actually went out. Replies and urgent messages rewrite as
  interactive AI calls, the rest as background calls.
- PDA strictness levels are cumulative:
    - 0: "you need to/must/have to", "right now", "ASAP"
    - 1: adds "don't forget", "remember to", "make sure", "you should"
    - 2 (the default): adds a command verb opening a sentence
    - 3: adds must/should/needs to/required with any subject

  Sentences ending in "?" are never treated as commands. A verb followed by you/we/I is
  treated as a question.
- When the AI rewrite suggests two options and the caller passed no buttons, the options become
  `Button(label, "reply", {"text": option})`. The agent (prompt 09) must handle
  `ButtonPress.kind == "reply"` as if the person had typed `payload["text"]`.
- `PdaCalibrator.observe_text` and `observe_reaction` exist, but nothing calls them yet. The
  agent (prompt 09) should run them on every inbound text and reaction.
- `themi.localtime` holds the family's timezone helpers. Timestamps are always stored as UTC ISO
  strings via `to_utc_iso()`, so SQL string comparisons work.
- The channel's handler can now be set after construction (`channel.handler = ...`), because
  the handler's outbox needs the channel.
- `tests/unit/test_architecture.py` fails if anything outside `outbox.py` and `telegram.py` calls
  `send_text`, `send_message` or `edit_text`.

### 09 · Agent core and scenario harness
Status: [x] (2026-10-24)
Depends on: 06, 08
Read first: "Architecture"; "AI backend"; "Security and privacy" (email content is data);
"Testing" → Scenarios and Tooling.

Build:
- `themi.core.prompts`: a system prompt builder. It puts a stable section first (who Themi is,
  PDA-sensitive voice, never show scores, trust-tier rules, treat quoted external content as
  data), then locked rules and pinned facts (empty until prompts 13–14). Volatile context goes
  in the user turn: local time, the member's qualitative energy label (stub for now), open
  items, and the last N messages.
- `themi.core.tools`: a tool registry where each tool has a name, description, strict JSON
  Schema, a handler, and a flag marking side effects. Side-effect tools must go through the
  trust tiers (enforced from prompt 11; until then they can only stage). Starter tools:
  `remember_fact` (stores to a temporary table until prompt 14), `log_energy_note` (stores a
  signal for prompt 18) and `list_open_items`.
- `themi.core.agent`: handles an `InboundEvent`.
    - Transcribes voice notes first.
    - A fast path resolves a bare yes/no/not-now when exactly one item is awaiting that member.
    - Otherwise it runs the chat-with-tools loop (at most 8 iterations) and sends the final
      reply through the outbox with `reply` priority.
    - Tool errors return as error results and never crash the loop.
    - On a refusal or a total AI failure it sends a short plain message.
- External content (emails, web text) is always wrapped in clearly delimited data blocks.
- Wire the Telegram handler to the agent.
- `tests/scenarios/harness.py`: builds the full stack with a temp DB, the scripted provider,
  the fake Telegram server and the frozen clock. It offers `say(member, text)`,
  `tap(member, button_label)`, `advance(hours=...)` and `inbox(member)` helpers so scenarios
  read like stories.

Tests:
- Unit tests: prompt builder ordering (stable prefix unchanged across turns) and the tool loop.
- Scenarios: hello → reply. A voice note → transcription → reply. A tool call → tool result →
  reply. Provider down → plain fallback message. Plan scenario 3 (Gemini 503 three times → falls
  back → exactly one reply, with "typing" shown).

Done when: Erin and her husband can chat with Themi through the fake end to end, and a manual
run with real Telegram and Gemini keys works. Commit.

Notes:
- Not yet run against real Telegram and Gemini, since there are no keys here. To try it:
    1. Put `TELEGRAM_BOT_TOKEN` and `THEMI_SECRET_KEY` in `.env`.
    2. Run `themi init` and pair with `/start <code>`.
    3. Add a Gemini key to the default backend. There's no website yet (prompt 16), so use a
       Python shell: `AISettingsStore(db, cipher).update_backend(SYSTEM, <backend id>,
       api_key=Secret("..."))`. The default backend is created on first use; until a key is
       added, the bot replies with SETUP_NEEDED_TEXT.
    4. Run `themi bot`.
- `themi.app.build_app(db, cipher, make_channel, provider_factory=, sleep=)` builds the whole
  graph and sets `channel.handler = agent`. Prompt 10's `themi run` should use it.
- Services (`themi.core.services.Services`) are where later prompts plug in:
    - `awaiting_sources`: callables returning `AwaitingItem(key, summary, resolve)`, used by the
      yes/no fast path (prompts 12 and 13).
    - `button_handlers[kind]` for button taps (`approval` in prompt 12, `rule` in prompt 13).
    - `reaction_handlers` for ✅ and 💤 (prompt 12).
    - `open_item_sources`.
    - `rules()` (prompt 13) and `facts_for(member)` (prompt 14). For now `facts_for` returns the
      last 20 `scratch_facts`.
    - `energy.label(member)` (prompt 18).
- Migration 0006 already creates `energy_signals` (source, value from -3 to +3, note).
  Prompt 18 should add to that table, not create it.
- `scratch_facts` is temporary; prompt 14 migrates its rows into the memory store.
- `list_open_items` includes queued outbox messages.
- The yes/no fast path only fires when exactly one item is waiting on that member. Otherwise
  "yes" goes to the model.
- Fix found by the scenarios: `channel.typing()` now sends the first chat action right away.
  Before, a fast reply cancelled the indicator before it ever showed.
- The router's `factory` now defaults to `build_provider` when given `None`, so `app.py` doesn't
  import adapters, which the architecture test forbids.
- Every canned reply (`SETUP_NEEDED_TEXT`, `BUSY_TEXT`, `DECLINED_TEXT`, `TANGLED_TEXT`,
  `VOICE_FAILED_TEXT`) passes the PDA checker at strictness 3.
- `tests/scenarios/harness.py`:
    - The `scenario` fixture gives every member the chain primary then fallback, for every task,
      using `ScriptedProvider`s at `scenario.primary` and `scenario.fallback`.
    - Helpers: `say`, `voice`, `tap(label)`, `advance(hours=, minutes=)`, `inbox`,
      `typing_shown`, and `clear_ai_settings(member)` to simulate a brand-new member.
    - The clock starts at Wed 21 Oct 2026, 09:00 Pacific.
- Prompt caching isn't explicitly enabled yet. The system prompt and the sorted tool list are
  stable, so adding `cache_control` to the Claude adapter later is cheap.

### 10 · Process runtime, scheduler, Docker
Status: [x] (2026-10-24)
Depends on: 09
Read first: "Deployment and hosting"; "Testing" → container smoke test.

Build:
- `themi run`: one asyncio process running the Telegram poller, the scheduler and the FastAPI
  app (uvicorn programmatic server), with graceful shutdown on SIGTERM.
- `themi.scheduler`: register periodic jobs (`every=timedelta`, jitter) and a durable
  `job_queue` table for deferred background work. Each job runs isolated (exceptions logged,
  never fatal). It uses the clock module, so tests can tick it manually with
  `scheduler.run_due()`. Release deferred outbox messages from here.
- `GET /health`: DB reachable, migrations current, poller alive.
- `Dockerfile`: `python:3.13-slim`, non-root user, `/data` volume for the DB, healthcheck.
  `docker-compose.yml` mounts `./data` and loads `.env`.
- CI: build the image and run a container smoke test (start it, wait for `/health`, stop it).

Tests:
- Scheduler: due jobs run, a failing job doesn't stop the others, deferred work is retried on
  the next tick and never dropped.
- Health endpoint.
- Graceful shutdown leaves no half-written state.

Done when: `docker compose up` runs Themi locally against real Telegram. This is the milestone 1
gate: both of you chatting with Themi on a local machine. Commit.

Notes:
- Not verified here:
    - Docker isn't installed on this machine, so the Dockerfile, compose file and
      `tools/smoke_container.sh` have only been syntax-checked. CI's `container` job will be the
      first real build.
    - The same check without Docker does pass:
      `tests/integration/test_runtime.py::test_themi_run_as_a_process_starts_and_stops_on_sigterm`
      runs `themi run`, waits for `/health` to return 200, sends SIGTERM and expects exit 0.
    - Real Telegram is still untested, since there's no token. The milestone 1 gate needs the
      user to run `docker compose up` with their bot token and a Gemini key.
- `themi run` replaces `themi bot`. `THEMI_DISABLE_TELEGRAM=1` runs it without polling, and
  `/health` then reports `telegram_poller: "disabled"`. This is used by the smoke tests. New
  settings: `THEMI_HTTP_HOST` (default 127.0.0.1, 0.0.0.0 in the image) and `THEMI_HTTP_PORT`
  (8080).
- `Runtime(app, host, port, telegram_enabled, scheduler_tick)` owns `.scheduler` and `.web` (the
  FastAPI app). Prompt 15 should add the website routes to `themi.web.create_app`, which takes
  `HealthSources` for now. Expect to widen it to the whole App.
- Scheduler: `scheduler.every(name, interval, fn, jitter=)` for periodic work.
  `@scheduler.handler(kind)` plus `scheduler.enqueue(kind, payload, run_after=, dedupe_key=)` for
  durable jobs.
    - A handler that raises the router's `Deferred` is re-queued after `retry_after` (default
      5 min). Deferrals never count as failures.
    - Other exceptions back off (1 min, 5 min, 30 min, 2 h) and fail after 8 attempts.
    - Registered periodic jobs: `outbox.flush` every 30 s. Later prompts register theirs in
      `Runtime.__init__`, or better, in a registration hook.
- Shutdown order:
    1. The stop event is set.
    2. The poller abandons a long poll (safe, because the offset is unchanged), and a batch
       being handled finishes.
    3. The scheduler finishes its current tick and HTTP stops.
    4. The Telegram client closes, the outbox flushes once more, and the database closes.

  There's a 30 s grace period before tasks are cancelled; compose allows 45 s.
- Image: `python:3.13-slim`, non-root uid 10001, `/data` volume, a HEALTHCHECK using
  urllib. Compose uses the named volume `themi-data`, not a bind mount, so the non-root user
  can write to it.
- `TelegramChannel.last_poll_at` feeds `/health`. A poller counts as stalled after 2 minutes
  without a completed poll.

---

## Milestone 2: Trust and memory

### 11 · Trust tiers engine
Status: [x] (2026-10-24)
Depends on: 09
Read first: "Trust tiers, rules and context repair"; "Testing" → Trust tiers row.

Build:
- Migration for `action_categories` (seeded with the plan's table, tiers and caps) and
  `pending_actions`, plus an append-only `action_audit` table.
- `themi.autonomy`:
    - `stage(category, member, summary, payload, executor)`: runs immediately at Tier 2 (and
      records it), otherwise creates a pending action and returns its id.
    - `resolve(id, decision, by_member)` with decisions approve, decline and snooze.
    - An executor registry. Executors are idempotent and receive the payload.
    - `grant_tier2(category, via_rule_id)` refuses capped categories.
    - `escalate(category, reason)` (Tier 3 behaviour) drops to Tier 1 until `resume(category)`.
- Snoozed items resurface later, via the receptivity hook.
- Make side-effect tools in the registry call `stage` instead of acting directly. Add a test
  that fails if any side-effect tool bypasses it.

Tests:
- Every state transition. A capped category can never reach Tier 2. Escalation and resume.
  Executor failures leave the action in a retryable state. The audit log is complete.
- Only the member an action belongs to (or an admin, for family-level categories) can resolve it.

Done when: there's no path from a tool to a side effect that skips the tiers. Commit.

Notes:
- Category keys (migration 0008):
    - Can become automatic: `email_mark_read`, `email_archive_noise`, `grocery_list_add`,
      `calendar_write`.
    - Capped at Tier 1: `email_reply`, `safeway_cart`, `doordash_order`, `vendor_call`,
      `habit_trial`.

  A CHECK constraint (`tier <= max_tier`) means even raw SQL can't make a capped category
  automatic.
- Scope, a refinement of the plan's "or an admin, for family-level categories": household
  actions (`grocery_list_add`, `calendar_write`, `safeway_cart`, `doordash_order`) can be
  answered by their owner or any admin. Personal ones (email, vendor calls, habits) only by
  their owner, not even an admin, because they act on that person's inbox or behalf.
  `open_for(member)` follows the same rule.
- API: `Autonomy(store, executors)`.
    - Staging and resolving: `await stage(category, member, summary, payload, executor)` and
      `await resolve(action_id, Decision.APPROVE | DECLINE | SNOOZE, by=, snooze_for=)`. Both
      return an `Outcome(action, message)`, where `message` is a short PDA-safe line for the
      person.
    - Tiers: `grant_tier2(name, via_rule_id=, by=)` and `revoke_tier2` (admin only, capped
      categories raise `CappedCategory`). `escalate(name, reason)` (no actor; it's the system)
      and `resume(name, by=)` (admin only).
    - Escalation keeps the grant but makes `effective_tier` SUPERVISED until `resume`.
    - Lookups: `open_for`, `awaiting` (pending only), `resurface_snoozed()` (call it from the
      scheduler; it returns actions so prompt 12 can re-send them) and `audit_trail()`.
- Executors: `executors.register("gmail.archive")(async fn(payload, ctx) -> str)`.
  `ctx.idempotency_key == f"themi-action-{id}"`; pass it to any external API that supports
  idempotency. A failed execution leaves the action `failed`, and approving it again retries.
  Automatic actions that fail are left open the same way.
- Tool side: `@staged_tool(name, description, properties)` handlers return
  `Proposal(category, summary, executor, payload)`. The registry stages it and tells the model
  either "Staged for approval (action N)... don't describe it as done", "Done automatically
  ...", or that it failed. `ToolRegistry.register` refuses `side_effect` tools without
  `proposes`, and the reverse. The old `side_effect=` argument on `@tool` is gone.
- `Database.update()` returns a rowcount. Approval claims the action atomically
  (`WHERE status IN (...)`), so a double tap can't execute twice.
- `action_audit` has no foreign keys (it outlives member deletion) and triggers block UPDATE and
  DELETE. Details are kept short (summaries, error class names).
- Not done here, as planned for prompt 12: Telegram approval messages, the yes/no fast-path
  source, reactions, /pending, stale-approval expiry, and scheduling `resurface_snoozed()`.

### 12 · Approvals in Telegram
Status: [x] (2026-10-24)
Depends on: 11
Read first: "How the family uses Themi" → In Telegram (approvals, reactions); "Testing" →
Telegram row.

Build:
- Approval messages go through the outbox: a summary plus **[Go ahead] [Not now]** buttons.
  ✅ on the message approves and 💤 snoozes.
- The result is reported by editing the original message, so the thread stays tidy.
- `/pending` lists open approvals with buttons.
- The yes/no fast path (prompt 09) resolves the single awaiting item.
- Expire stale approvals after a configurable time, with a quiet note.

Tests (scenarios):
- Stage, tap Go ahead, executor runs and the message is edited.
- A 💤 reaction snoozes, and the item resurfaces after time advances.
- The partner's tap on someone else's approval is rejected.
- `/pending` with several items.

Done when: the scenarios pass. Commit.

Notes:
- `themi.core.approvals.ApprovalsUI(autonomy, outbox, ttl=3 days)`. `install(services)` adds:
    - an autonomy pending listener,
    - `button_handlers["approval"]`,
    - a reaction handler: ✅ 👍 👌 approve, 💤 ⏰ snooze,
    - an awaiting source for the yes/no fast path,
    - the `/pending` command.

  `ApprovalsUI.resolve(action_id, decision, by)` is the one entry point. It edits every
  approval message for that action to show the result. The website (prompt 15) should call it
  too, so Telegram messages get tidied when someone approves on the site.
- "Not now" and 💤 snooze, which is gentler than declining. "no", "nope", "skip it" and
  "leave it" decline. The agent now has `LATER_WORDS`, and `services.Decision` is
  yes/no/later.
- Priority: `autonomy.stage(..., interactive=True)` is set by staged tools during a
  conversation, and sends the approval as `Priority.REPLY` even in quiet hours. Background
  staging uses `NORMAL`. An approval answered before its queued message went out has that
  message withdrawn (`outbox.cancel`).
- Messages: approval messages are tracked in `approval_messages` (action to outbox row), and the
  Telegram message id comes from the outbox once sent. Edits go through `outbox.edit()`, which
  is shielded. The architecture test still forbids `edit_text` anywhere else.
- Commands: `services.commands["/name"] = async (member, argument) -> None`. Commands never go
  to the model; unknown ones fall through to it. Prompt 13 adds `/rules` and prompt 17 adds
  `/pause`, `/tracking` and `/site`.
- Periodic work is now declared on the App as `app.periodic: list[PeriodicTask]`, which the
  runtime registers:
    - `outbox.flush` every 30 s
    - `approvals.resurface` every 5 min
    - `approvals.expire` hourly

  Later prompts append to this list in `build_app`. The harness `run_periodic(name)` runs one
  by hand.
- Text gotcha found by the tests: "Nothing is waiting on you right now" was softened by the
  shield, because "right now" is a level-0 demand phrase. Canned texts must avoid demand
  phrases even when they're neutral. `test_approval_texts_pass_the_strictest_pda_check` guards
  this.
- Family-scope approvals go to the member who triggered them. Admins see them in `/pending`, and
  answering from there edits the owner's message too.
- Fix (2026-10-25, found in a `make dev` session, failing scenarios first): a bare "yes" went to
  the one waiting card even when Themi had asked a different question after it, so "yes, add it
  to my tasks" approved a grocery item the person had just turned down. `AwaitingItem` now
  carries the Telegram ids of the messages that asked it (`message_ids`, from
  `approval_messages` and `rule_messages`). The fast path skips an item if any later outbound
  message (not an edit) contains a "?"; the model gets the "yes" with the item still listed
  as waiting. The model has no tool to answer cards, so in that case the person uses the
  buttons or a reaction. That includes a card whose same-turn reply ends in a question.

### 13 · Rules: drafts and locking
Status: [x] (2026-10-24)
Depends on: 11, 12
Read first: "Trust tiers, rules and context repair" → Rule locking; "Testing" → Rules row and
scenario 2.

Build:
- Migration for `rules` (summary, text, kind: policy | autonomy_grant | standing_reminder,
  category, status draft | locked | expired | discarded, proposed_by, affects, timestamps).
- A `propose_rule` tool creates or updates a draft and sends the proposal message: *"Proposed
  Rule: [summary]. A YES locks this in, or we keep brainstorming."* with a **[Lock it in]**
  button.
- Locking requires a YES or a tap from the affected member. A partner's YES does not lock it.
  Locking an `autonomy_grant` rule calls `grant_tier2`, which respects caps.
- Drafts expire quietly after 14 days (scheduler job).
- `/rules` lists locked rules and drafts.
- The prompt builder includes all locked rules in the stable section of every request.

Tests:
- Plan scenario 2 (the partner's YES doesn't lock, Erin's does).
- Expiry. An autonomy grant on a capped category is refused with a gentle explanation.
- The scripted provider's recorded request contains the locked rule text.

Done when: the scenarios pass. Commit.

Notes:
- Safety decision: the model can propose rules, but there's no lock tool. A rule locks only
  when the affected member taps [Lock it in] or sends a bare YES while it's the only thing
  waiting on them. If an approval and a draft are both waiting, "yes" goes to the model, which
  can only point them at the button.
- `affects` is always the proposer, for now. A household rule proposed by Erin is locked by
  Erin. Prompt 34 (the family group) may want rules both partners agree to.
- Autonomy-grant proposals are checked up front. A capped category or a non-admin proposer gets
  a gentle "Not proposed: ..." tool result and no draft. Locking re-checks through
  `grant_tier2`.
- `Rulebook`:
    - Lifecycle: `propose`, `lock(rule_id, by)` and `discard`. Each edits every proposal message
      for that rule.
    - `unlock(rule_id, by)` is for the website (prompt 16) and revokes an autonomy grant.
    - `add_standing_reminder(member, summary, text)` creates a locked rule directly. It's for
      context repair (prompt 14), which the person explicitly asked for.
    - Lookups: `locked()`, `locked_texts()` and `drafts(member)`.
- The system prompt now says to capture rules with `propose_rule` and never treat drafts as
  agreed. Locked rule texts are appended in order (`Services.rules()` reads
  `rulebook.locked_texts()`). This changes the cached system prefix only when a rule is locked
  or unlocked.
- Periodic: `rules.expire_drafts` runs hourly. A draft lapses 14 days after its last update.
- New statuses: `discarded` (said no), `expired` (lapsed) and `unlocked` (retired later).

### 14 · Memory and context repair
Status: [x] (2026-10-24)
Depends on: 13
Read first: "Trust tiers, rules and context repair" → Context repair; "Testing" → Context
repair row and scenario 5.

Build:
- Migration for `facts` (family or member scope, subject, fact, pinned, source, timestamps)
  with an FTS5 index, and `context_repairs` (complaint, diagnosis, fix, timestamps). Move
  prompt 09's temporary `remember_fact` storage here.
- Retrieval: pinned facts always go in the prompt. Unpinned facts are retrieved by FTS match
  against the incoming message (top 5).
- A `report_forgotten_context` tool runs the four-way diagnosis:
    - never stored → store pinned
    - stored but not retrieved → pin
    - stored wrong → correct
    - included but ignored → promote to a `standing_reminder` locked rule
  It replies with what it found and changed.

Tests:
- Each diagnosis branch.
- Plan scenario 5 (the cat's vet day is pinned and appears in the next request).
- Retrieval ranking basics.
- Repairs are logged.

Done when: the scenarios pass. Commit.

Notes:
- Facts have scope `family` (shared) or `member` (only in that member's conversations).
  `remember_fact` now takes `about: household|personal`. Migration 0011 moved `scratch_facts`
  rows in as household facts and dropped the table.
- Where facts go in the prompt, for caching: pinned facts go in the system prompt. The top 5
  full-text matches for the incoming message go in the user turn under "Possibly relevant
  things you were told before". `Services.facts_for(member, message)` returns `(pinned,
  notes)`.
- `last_shown_at` is stamped whenever a fact is placed in a prompt, pinned or retrieved. Context
  repair counts a fact as "included" if it's pinned or was shown in the last 2 days.
- Repair diagnosis:
    1. FTS-match the complaint plus the correction (top 3, pinned included).
    2. No match means `never_stored`: save it pinned.
    3. A correction whose word overlap with the stored fact is under 0.6 (Jaccard, stopwords
       removed) means `stored_wrong`: correct the fact and pin it.
    4. A match that wasn't recently shown means `not_retrieved`: pin it.
    5. Otherwise `ignored`: `rulebook.add_standing_reminder(...)` creates a locked rule
       "Always keep in mind: ...".

  The tool returns the diagnosis plus a message for the model to relay in its own words. All
  repairs are logged in `context_repairs`.
- Search uses FTS5 with the porter tokenizer, so "refilling" finds "refilled". Query terms are
  meaningful words joined with OR and ranked by bm25. FTS5 is confirmed available in Python
  3.12 (SQLite 3.45) and 3.15 (SQLite 3.54).
- `Memory` methods for the website (prompt 16): `visible(member)`, `pin(id, pinned)`,
  `correct(id, text)`, `forget(id)` and `repairs(member_id)`. None of these check permissions
  yet; the website should only let members edit household facts and their own personal facts.
- Tooling: ruff's SIM905 autofix had flattened word lists (`"""...""".split()`) into
  one-word-per-line lists. It's now ignored in `pyproject.toml`, and the PDA verb list is
  restored.

### 15 · Website v1: sign-in, dashboard, personal settings
Status: [x] (2026-10-24)
Depends on: 10, 11
Read first: "How the family uses Themi" → The management website; "Security and privacy" →
Website.

Build:
- `themi.web`: Jinja2 templates, HTMX (vendored), mobile-first CSS with no build step, light and
  dark themes.
- Auth via a one-time login link. A login-link service creates single-use tokens that expire in
  10 minutes. Sessions use secure, HttpOnly, SameSite=Lax cookies. All POSTs carry CSRF tokens.
  Google sign-in comes in prompt 21.
- Pages:
    - dashboard: pending approvals (approve or decline inline), recent activity, alerts
    - my settings: quiet hours, daily limit, PDA shielding on/off and strength, tracking-input
      toggles

Tests (FastAPI TestClient):
- Link expiry and single use.
- CSRF rejection.
- A member can't see or modify the other member's settings.
- An approval from the dashboard runs the executor.

Done when: a member can sign in from a link and manage their own settings. Commit.

Notes:
- Login links:
    - Opening `GET /login/{token}` only shows a Continue button. `POST /login/{token}` consumes
      the token. That's deliberate: Telegram fetches link previews, which would otherwise burn
      the link. Prompt 17's `/site` should still send with link previews disabled.
    - `WebAuth(store).create_link_token(member)` makes a link (10 minutes, single use, stored as
      a SHA-256 hash).
    - `themi login-link <name>` prints `{base}/login/{token}`. `site_base_url()` uses
      `THEMI_PUBLIC_URL` when set, otherwise `http://127.0.0.1:<port>`.
- Sessions:
    - `web_sessions` holds token hashes with a sliding 30-day expiry and a per-session CSRF
      token.
    - The cookie `themi_session` is HttpOnly and SameSite=Lax, and Secure only when
      `THEMI_PUBLIC_URL` is https. Local http dev therefore works, while Tailscale Funnel gets
      Secure cookies.
- CSRF: every POST needs a `csrf` form field or an `X-CSRF-Token` header. `base.html` sets
  `hx-headers` so HTMX requests carry the header automatically. A missing or wrong token
  returns 403 with a friendly "page was out of date" message.
- Pages:
    - `/`: open actions with Go ahead, Not now and Leave it; the last 12 outcomes; admin
      escalation alerts; and failed-action notes.
    - `/settings`: personal settings only.
    - `/signed-out`, `/logout` (POST).
    - Approvals go through `app.approvals.resolve`, so the Telegram message gets edited too.

  Routes never take a member id, so there's nothing to tamper with, and a `member_id` field
  posted in a form is ignored.
- Assets:
    - HTMX 2.0.11 is vendored at `web/static/htmx.min.js`. Its SRI hash was checked against
      htmx.org's published value; 2.0.4 is no longer shown in their docs.
    - A strict CSP allows `'self'` only. The `htmx-config` meta tag turns off injected indicator
      styles so the CSP holds.
    - Templates and static files ship in the wheel (checked).
- Structure:
    - `install_site(web, SiteContext(app, base_url, secure_cookies))` is called from
      `create_app` when a `SiteContext` is passed. Prompt 16 should add its pages in
      `themi/web/site.py` or a sibling module, using the same `current`, `checked` and `page`
      helpers. Consider moving them to a small module once there are more routers.
    - `Runtime` now takes `public_url` and builds the `SiteContext`.
- Tests: the `scenario` fixture moved into `tests/scenarios/harness.py`, which is registered as a
  pytest plugin, so integration tests can use the full app too. Website tests drive the
  FastAPI app over `httpx.ASGITransport` in the same event loop as the fakes; `TestClient`'s
  separate loop would clash with the PTB client.
- New runtime dependencies: jinja2 and python-multipart.
- Not done here: Google sign-in is prompt 21, and the admin, tiers, rules and AI pages are
  prompt 16.

### 16 · Website v1: admin, tiers, rules, AI backend pages
Status: [x] (2026-10-24)
Depends on: 06, 13, 14, 15
Read first: "How the family uses Themi" → management website; "AI backend" (per-member backend
paragraph).

Build:
- Family (admin only): members, roles, invites, timezone, takeout budget, staples list.
- Trust tiers: each category with its tier, an auto toggle (only where allowed, and turning it
  on creates and locks an `autonomy_grant` rule on behalf of the admin), and a resume button
  for escalated categories.
- Rules and memory: locked rules, drafts, facts (pin, unpin, edit, delete), repair log.
- AI backend (per member, self-service): provider and model per task, a fallback chain editor,
  API key entry (write-only, stored encrypted, shown masked), and a connection test button.

Tests:
- Admin-only enforcement.
- Keys never rendered back.
- Toggling auto on a capped category is impossible.
- Connection test success and failure against the scripted provider.

Done when: every setting named in the plan's website section exists. Commit.

Notes:
- Pages:
    - `/family`: admins only (403 "Admins only" for members).
    - `/tiers`: everyone can see it; only admins can change it.
    - `/knowledge`: rules and memory.
    - `/ai`: self-service AI settings.
    - The nav shows Family only to admins.
- Page modules (`admin_pages.py`, `knowledge_pages.py`, `ai_pages.py`) each expose
  `routes(kit) -> APIRouter`. `Kit` (in `themi.web.kit`) provides:
    - `current(request)` and `admin(request)`
    - `await checked(request, admin=)`, which checks CSRF and returns `(session, form)`
    - `page(...)`, `with_flash(request, template, session, ...)` and `redirect(url, message)`

  New pages should follow the same pattern.
- Tiers:
    - "Make automatic" calls `rulebook.grant_automatic(admin, category)`. That creates a locked
      autonomy-grant rule ("Automatic: <label>") in the admin's name; ticking the switch counts
      as the explicit confirmation.
    - "Ask first again" calls `revoke_automatic`, which retires that rule.
    - Capped categories render no button, and a forged POST gets the "always needs a yes"
      explanation.
- My AI:
    - Keys are write-only. The form shows "saved (leave blank to keep)" or "not set", and never
      any characters of the key.
    - A blank key keeps the saved one; ticking "Remove saved key" clears it.
    - Chains have up to 3 slots, each with an optional model override.
    - "Test the first choice" calls `router.test_connection` (HTMX-friendly).
    - Gemini backends show the free-tier data-use note.
    - The page calls `ensure_defaults`, so new members see the keyless free-tier backend.
- Memory edits go through `Memory.can_edit`: household facts can be edited by anyone, personal
  facts only by their owner. Forged POSTs for someone else's personal fact are refused.
- Flash messages are URL-encoded in the cookie, because invite instructions contain line
  breaks. `.flash` uses `white-space: pre-line`.
- Test helpers: `tests/fixtures/web.py` (a plugin) provides the `site` fixture plus
  `web_client`, `sign_in` and `csrf_of`.

### 17 · Chat commands: /pause, /tracking, /site
Status: [x] (2026-10-24)
Depends on: 15
Read first: "How the family uses Themi" → Chat commands; "Security and privacy" → Transparency.

Build:
- `/pause [topic] [duration]` with natural-language equivalents via a tool. Topics map to
  outbox message kinds. Pauses expire automatically.
- `/tracking` lists, in plain words, every input Themi watches about the member asking, with
  toggle buttons. It never reveals the partner's data.
- `/site` sends a one-time login link (prompt 15).
- `/link gmail` is a stub that says it's coming (prompt 21 replaces it).
- Register all commands with Telegram (`setMyCommands`).

Tests:
- Pause suppresses and then resumes the right kinds.
- Tracking toggles take effect and are reflected on the website.
- The /site link works exactly once.

Done when: the commands work end to end in scenarios. This is the milestone 2 gate. Commit.

Notes:
- Pause topics map to outbox `kind`s (`themi.channels.pauses.TOPICS`):

  | Topic | Kinds |
  | --- | --- |
  | meals | meal |
  | laundry | laundry |
  | maintenance | maintenance |
  | tasks | task |
  | habits | habit |
  | approvals | approval, rule |
  | notes | relay |
  | everything | every proactive message |

  Later prompts must send their proactive messages with these kinds: prompt 20 uses `task` and
  `habit`, 31 `laundry`, 33 `maintenance`, 34 `relay`, 35 `meal`.
- How pauses behave:
    - A pause holds normal and low messages of matching kinds until it ends. Nothing is dropped.
    - A pause outranks a deadline, because the person explicitly asked.
    - Replies and urgent messages are never held.
    - `/resume` calls `outbox.release_held(member)`, so held messages are re-evaluated at the
      next flush (quiet hours and limits still apply).
- Durations: today (until local midnight, the default), tonight (until the end of quiet hours),
  tomorrow, Nh/Nd/Nw/Nm, "a week", "an hour". The maximum is 30 days. Plain-words equivalents
  are the `pause_messages` and `resume_messages` tools.
- Commands:
    - Register with `services.add_command(name, handler, description)`. `/pending` and `/rules`
      were moved onto it.
    - `services.command_menu()` feeds `TelegramChannel.publish_commands`, which is called after
      start in the runtime and the harness.
    - `/help` lists `services.command_help`.
- `/tracking` shows only the asker's own inputs. Its buttons (`kind="tracking"`) toggle a setting
  and edit the list in place. The website's settings page reflects the change.
- `/site` sends `{services.site_url}/login/{token}` with `link_preview=False`, which becomes
  Telegram's `link_preview_options.is_disabled`. `Runtime` sets `services.site_url` from
  `THEMI_PUBLIC_URL`, or the local address. Outbox rows have a new `link_preview` column.
- `/link` is a stub (`LINK_SOON`). Prompt 21 replaces the handler with the Google flow.
- Milestone 2 gate: the code is complete. Real-world use waits on the milestone 1 setup (bot
  token, Gemini key).

---

## Milestone 3: Shadow Calendar

### 18 · Energy signals and capacity model
Status: [x] (2026-10-24)
Depends on: 09, 17
Read first: "Module behaviour" → B; "Testing" → Energy engine row.

Build:
- Migration for `energy_signals` and `energy_baseline` (member, hour of week, mean, n).
- Inputs, each honouring the member's tracking toggles:
    - explicit notes via `log_energy_note` (the AI extracts a drain/boost value from −3 to +3)
    - message timing and reply latency (passive)
    - a device-activity hook for Phase 2
- `themi.energy.model`:
    - capacity from 0 to 100 = hour-of-week baseline (with a sensible prior curve until there's
      data) + recent signals decaying with the member's recovery speed (half-life in hours)
    - a qualitative label for user-facing text ("seems like a low day", "steady", "good stretch")
- A lint test that fails if any user-facing template or prompt section contains a numeric score.
- The prompt builder now passes the real qualitative label.

Tests:
- Decay math against the recovery speed.
- Hypothesis: capacity always stays within 0–100 for arbitrary signal sequences.
- Toggles disable inputs.
- Labels map from ranges.
- No scores in output.

Done when: capacity is computed for both members and is visible only as words. Commit.

Notes:
- `themi.energy.model.EnergyModel(store)` is `services.energy` in `build_app`.
    - `capacity(member, at=)` is the number, for `themi.energy` only.
    - `label(member)` gives the words.
    - `baseline(member, at=)` and `signals(member, at=)`.
    - `record(member, source, value, note)` returns False if the input is switched off.
    - `observe_inbound(member)` and `observe_device_activity(member, value, note)`.
- Maths:
    - capacity = clamp(baseline + Σ value × 8 × 0.5^(age h / recovery_hours)).
    - Signals older than 72 h are ignored.
    - Baseline = n/(n+3) × learned mean + 3/(n+3) × prior, where the prior is `PRIOR_CURVE` by
      local hour.
    - Hour of week runs 0–167 from Monday 00:00 local.
- Reply latency is measured against the latest sent normal or low outbox message:
    - within 10 min: +0.5
    - within 2 h: 0 (recorded, so it isn't counted twice)
    - within 12 h: -0.5
    - later: nothing

  Notes look like `outbox:<id>`, one per message.
- Labels:

  | Capacity | Label |
  | --- | --- |
  | under 25 | "running low today, it seems" |
  | 25 to 45 | "seems like a low stretch" |
  | 45 to 65 | "steady" |
  | 65 to 80 | "seems to have some energy" |
  | 80 and up | "seems to be in a good stretch" |
  | every input off | "no read (they've turned energy tracking off)" |
- Structural guards in `test_architecture.py`:
    - No `.capacity(`, `.combine(` or `.baseline(` calls outside `themi/energy`. Prompts 19 and
      20 (windows, matching) should live in `themi/energy` too.
    - Templates never contain "capacity" or "score".
- `energy_baseline` exists, but nothing writes to it yet; prompt 19's outcome learning fills it.

### 19 · Good windows and outcome learning
Status: [x] (2026-10-24)
Depends on: 18
Read first: "Module behaviour" → B (learning); "How the family uses Themi" (quiet by default).

Build:
- `themi.energy.windows`: predict good windows for the next 24 hours per member (projected
  capacity at or above the receptive threshold, outside quiet hours), plus `next_window(member)`.
- Outcome tracking: every proactive prompt records acted, snoozed or ignored. Ignored means no
  response within a timeout that depends on the prompt kind. The outcome updates the baseline
  for the hour of week it was sent (EMA with a decreasing learning rate and a floor).
- Replace the outbox's stub `ReceptivityProvider`: `normal` waits for a window, `low` waits for
  a strong window, and anything past its deadline sends at the next allowed time.

Tests:
- Window prediction on synthetic baselines.
- Learning moves the baseline toward the outcomes.
- Deferral to windows with the frozen clock.
- Deadlines honoured.

Done when: proactive messages are timed by the model. Commit.

Notes:
- `themi.energy.windows`:
    - `windows(model, member, start, threshold=, horizon=)` and
      `next_window(model, member, start, threshold=)`, using 15-minute steps over 24 h.
    - Thresholds: `RECEPTIVE = 45` (steady) and `STRONG = 60`.
    - If nothing clears the bar, `next_window` returns the best non-quiet moment in the
      horizon, so nothing waits longer than a day.
    - `EnergyReceptivity(model)` is the outbox's receptivity in `build_app`. Normal messages
      use RECEPTIVE and low ones STRONG. A member with every input off is never held back.
- `themi.energy.outcomes.OutcomeTracker`:
    - Recording: `on_sent(row, message_id)` is an outbox `sent_listeners` hook for normal and
      low messages.
    - Resolving: `observe(member, event)` is called by the agent for every inbound event. A
      button or reaction resolves its own message, anything else the latest open one. "not
      now", 💤 and snooze buttons count as snoozed.
    - Expiry: `expire()` is the periodic task `energy.expire_outcomes`, every 15 min.
    - Learning: `learn(member_id, hour, outcome)` moves the baseline toward acted 75, snoozed
      45, ignored 25, with step max(0.1, 1/(n+1)).
    - `recent_rate(member_id, days=14)` returns the share acted on. Prompt 20's habit reserve
      should use it.
- Respond-by timeouts per kind:

  | Kind | Respond by |
  | --- | --- |
  | approval | 6 h |
  | rule | 12 h |
  | meal | 2 h |
  | laundry | 3 h |
  | task | 8 h |
  | maintenance | 24 h |
  | habit | 12 h |
  | relay | 8 h |
  | anything else | 3 h |
- Interaction with the prior: the first outcome sets that hour's learned mean to the target
  outright (step 1), but `EnergyModel.baseline` still blends n/(n+3) with the prior. So one
  outcome moves the effective baseline about a quarter of the way.
- `app.py` has a small `_async()` wrapper for synchronous periodic jobs.

### 20 · Tasks, matching, habit reserve
Status: [x] (2026-10-24)
Depends on: 19
Read first: "Module behaviour" → B (task matching, reserve habits); "Testing" → scenario 1.

Build:
- Migration for `tasks` and `habits`.
- Tools: `create_task` (title, kind: text | call | physical | errand, effort 1–5, optional due
  date), `complete_task` and `snooze_task`.
- `themi.energy.matching`:
    - The default owner comes from kind (text tasks to Erin, calls to her husband), configurable
      in family settings.
    - Swap to the partner when the partner's spare capacity minus the hand-over cost exceeds
      the default owner's spare capacity. Per-member kind cost multipliers and recovery speed
      both count.
    - Record the reason for each assignment.
- Task prompts are two-option button messages via the outbox at the assignee's window.
- Habit reserve: offer at most one habit every 14 days, only when recent prompts are mostly
  acted on, staged through the `habit_trial` category. Habits that keep being ignored are
  retired quietly.

Tests:
- Matching table tests (no swap, swap, swap blocked by the hand-over cost).
- Plan scenario 1 (Erin's draining note routes the next task to her husband and her reply has
  no score).
- Habit offering conditions and retirement.

Done when: the scenarios pass. This is the milestone 3 gate. Commit.

Notes (2026-10-24):
- Migration `0016_tasks_habits.sql`:
    - Adds `family.task_owners` (kind → member id; the seed has text → Erin, call →
      husband) and `family.handover_cost` (default 10, 0–50).
    - Adds `members.kind_costs` (kind → multiplier, 0.25–4).
    - Adds the `tasks` and `habits` tables.
    - `update_family` and `update_settings` validate the new fields.
- `themi.energy.matching`:
    - Cost = effort × 8 × kind multiplier × recovery factor.
    - Recovery factor = 1 + (half-life − 6 h)/24, clamped to 0.75–1.5.
    - Spare = capacity − cost.
    - A swap needs spare(partner) − handover > spare(default).
    - Kinds with no owner go to the requester.
    - If the default owner has every energy input off, the task never swaps (the reason says
      so). Untracked partners are never swapped to.
    - Reasons are words only, e.g. "Usually Erin's (texting), but Husband seems to have more
      room right now."
- `themi.core.tasks.TaskBoard`:
    - The tools tell the model who got the task and why.
    - Nudges are NORMAL `kind="task"` messages with Done / Later buttons. The deadline is
      09:00 local on the due date.
    - Later snoozes for 4 h; the periodic job `tasks.resurface` (15 min) brings it back.
    - Completing or snoozing withdraws a nudge that hasn't gone out yet.
    - Open tasks are listed among the person's open items.
    - Prompt texts never open a sentence with the title, because titles are usually commands.
- `themi.core.habits.HabitReserve`:
    - Four seed ideas per member.
    - `habits.offer` (6 h) offers only when all of these hold:
        - no offer is open
        - nothing was offered in the last 14 days
        - there are at least 5 resolved outcomes in the last 14 days, and at least 70% were acted on
    - Offers are staged through `habit_trial` with the executor `habits.activate`.
      Declined or lapsed offers are settled as declined and never made again.
    - `habits.send` (1 h) sends one LOW `kind="habit"` message a day. It waits until the
      previous message is resolved, and retires the habit silently after 3 ignored in a row.
- `OutcomeTracker` gains `recent()` and `outcome_of(outbox_id)`.
- The architecture guard flags any `.combine(` call outside `themi.energy`, so
  `datetime.combine` is avoided elsewhere.
- Follow-up: task owners, hand-over cost and per-person kind costs can only be set in code or
  by the store for now. They belong on the website's family and personal settings pages.

---

## Milestone 4: Gmail and pantry

### 21 · Google sign-in and account linking
Status: [x] (2026-10-24)
Depends on: 16
Read first: "Integrations" → Gmail row and the Gmail sign-in note; "Setup checklists" (Google
Cloud items); "Security and privacy".

Build:
- `themi.connectors.google.oauth`: authorization-code flow with PKCE and state, via `httpx`
  against configurable Google endpoints. Scopes: `openid email`, `gmail.modify`,
  `calendar.events`. Check Google's current docs for exact scope strings and the rules for
  unverified "in production" apps, and record what you find in Notes.
- Website: "Sign in with Google", restricted to member email addresses (members gain an email
  field).
- Linking: `/link gmail` and a website button start the flow for the current member. Each
  linked account stores the address and an encrypted refresh token. A member can link any
  number of accounts.
- Token refresh. Unlink revokes the token at Google and deletes the account's stored metadata.
- `tests/fakes/google_oauth.py`: fake authorize and token endpoints.
- README section: step-by-step Google Cloud setup matching the plan's checklist.

Tests:
- Full flow against the fake.
- State and PKCE mismatch rejected.
- A non-member Google account is refused sign-in.
- Refresh tokens are encrypted at rest.
- Revocation is called on unlink.

Done when: both members can link several Gmail accounts locally. Commit.

Notes (2026-10-24):
- Google's current rules, checked 2026-10-24:
    - Endpoints: `accounts.google.com/o/oauth2/v2/auth`, `oauth2.googleapis.com/token` and
      `/revoke` (form POST `token=`), and `openidconnect.googleapis.com/v1/userinfo`.
    - Exact scopes: `openid email`, `https://www.googleapis.com/auth/gmail.modify` (restricted)
      and `https://www.googleapis.com/auth/calendar.events`.
    - A refresh token needs `access_type=offline`. `prompt=consent` is forced, so a re-link
      always gets a new one.
    - A dead refresh token returns `invalid_grant`.
    - Unverified "in production" apps show a warning screen and have a lifetime cap of 100
      users for unapproved restricted scopes. Tokens don't expire.
    - Apps in "Testing" lose their refresh tokens 7 days after consent, unless they request
      only `openid email profile`.
    - Plain `http` redirect URIs are accepted only for `localhost`.
- `themi.connectors.google`:
    - `GoogleOAuth`:
        - Authorization-code flow with S256 PKCE.
        - The state is kept hashed in `oauth_states` (migration 0017), with the verifier
          encrypted, for 10 minutes, and is single use.
        - The callback must come back to the redirect URI the state was issued for.
    - `GoogleAccounts`:
        - Sign-in needs a verified address that is a member's sign-in address.
        - Linking needs the `gmail.modify` scope (people can untick it) and a refresh token.
          A refused grant is revoked, never left dangling.
        - A member can link any number of accounts. Re-linking an address replaces the token
          and re-enables the account. An address already linked by another member is
          refused.
        - Access tokens are cached in memory and refreshed a minute before they expire.
        - `invalid_grant` on refresh disables the account (`enabled = 0`) and raises
          `TokenRevoked`. Prompt 22 should turn that into a gentle "link again" message.
- Sign-in addresses:
    - Members gain `email` (unique, case-insensitive).
    - Admins set it on the Family page (`store.set_email`).
    - A member's first linked Gmail becomes their sign-in address if they have none, since
      linking proves they own it.
- Website:
    - "Sign in with Google" appears on the signed-out and expired-link pages.
    - `/auth/google/callback` finishes both flows. A link started in Telegram works in a
      browser that isn't signed in, because the state carries the member.
    - The new *My accounts* page (`/accounts`) has link (a CSRF-checked POST that redirects
      to Google) and unlink.
    - The CSP `form-action` now includes Google's authorize origin, because browsers check
      redirects that follow a form POST.
- Unlinking:
    - It deletes the account first, then revokes at Google.
    - If Google can't be reached, the account is still forgotten, and the page tells the
      person where to finish revoking.
    - Removing a member on the Family page revokes all of their tokens.
- `/link gmail` replies with the Google consent URL, with no link preview, and lists accounts
  already linked. With no Google keys, it and the website say linking isn't set up yet.
- Settings:
    - `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` must be set together.
    - `GOOGLE_AUTH_URL`, `GOOGLE_TOKEN_URL`, `GOOGLE_REVOKE_URL` and `GOOGLE_USERINFO_URL`
      only exist for pointing at a fake.
    - `httpx` is now a declared dependency.
- Tests:
    - `tests/fakes/google_oauth.py` checks the client, the registered redirect, single-use
      codes, the PKCE S256 verifier and revocation. It can be run by hand (`python -m
      tests.fakes.google_oauth`), with a small consent form, for local trials.
    - The `scenario` fixture configures Google only when a test also asks for `fake_google`.
- Setup the user must do:
    - Follow the README's "Google Cloud setup" (project, APIs, consent screen published and
      unverified, web client with redirect `<THEMI_PUBLIC_URL>/auth/google/callback`) and put
      the keys in `.env`.
    - Locally, use `THEMI_PUBLIC_URL=http://localhost:8080`.

### 22 · Gmail connector and polling
Status: [x] (2026-10-25)
Depends on: 21, 10
Read first: "Integrations" → Gmail; "Testing" → Gmail row.

Build:
- `themi.connectors.gmail`: REST client (list and get messages, history.list, modify labels,
  send). Message parsing: headers, plain-text body (HTML stripped), attachments listed but not
  downloaded.
- A per-account polling job. The first run syncs the last N days, after that it uses
  `history.list` from the stored history id. If the history id expires, it resyncs.
- Accounts are polled independently, so one account's failure doesn't block the others.
- An expired or revoked token alerts the owning member via the outbox, once, until fixed.
- Executors for later tiers: mark read, archive, apply label, send reply.
- `tests/fakes/gmail_api.py`: a fake with a scriptable mailbox, history ids, and 401/429 responses.

Tests:
- Initial sync, incremental history, history-expired resync.
- Several accounts per member.
- A revoked token triggers exactly one alert.
- Executors call the right endpoints.

Done when: new mail in the fake reaches an internal `EmailReceived` event. Commit.

Notes (2026-10-25):
- `themi.connectors.gmail`:
    - `client.GmailClient` covers profile, messages list and get, history (messageAdded,
      INBOX), labels list and create, modify and send.
    - A 401 drops the cached access token and retries once. 429s (and 403
      `rateLimitExceeded`) raise `RateLimited` with Retry-After. A 404 on history raises
      `HistoryExpired`.
    - The base URL is `GoogleConfig.gmail_url` (env override `GOOGLE_GMAIL_URL`, for fakes).
- `parse.parse_message`:
    - Reads From (name and address), To and Cc, Subject, Message-ID and References.
    - The body is the first text/plain part, otherwise the text/html part with tags,
      scripts and styles stripped. Charsets are honoured, and bodies are capped at 20,000
      characters.
    - Attachments are listed only (name, type, size).
- `sync.GmailSync`, run by the periodic job `gmail.poll` (every minute; each account is due
  every 3 min):
    - First sync: the profile's history id is read before listing, then up to 200 INBOX
      messages from `newer_than:7d`, oldest first.
    - After that, `history.list` with every page read. The stored history id moves only
      after the last page, so an interrupted sync resumes without announcing anything
      twice (`emails` is unique per account and Gmail id).
    - Expired history means a fresh first sync.
    - Each account is polled independently. Errors back off 5 min, 15 min, 1 h, 3 h, and
      Retry-After is honoured.
    - Only accounts that are watched and enabled are polled.
- Lost access:
    - A dead token (refresh `invalid_grant` or a persistent 401) disables the account and
      sends one NORMAL `kind="system"` alert through the outbox ("/link gmail ... would fix
      it").
    - `alerted_at` stops repeats. Linking again clears it, along with the backoff
      (`set_linked_account_enabled(True)`).
- Storage: migration 0018 adds sync columns on `linked_accounts`, the `emails` table
  (removed with the account) and `email_sends`.
- `EmailReceived(account, email_id, message, initial)` is passed to `GmailSync.listeners`.
  `initial=True` marks mail found by a first sync or resync, not newly arrived. Triage
  (prompt 23) should register here and probably shouldn't alert on `initial` mail.
- Executors (`gmail.mark_read`, `gmail.archive`, `gmail.label`, `gmail.send_reply`):
    - Their payload is `{"email_id"}` (plus `label`, or `body` for replies), and they refuse
      mail from someone else's account.
    - Archive removes INBOX only; nothing is ever deleted.
    - Label creates the label once.
    - Send reply threads with In-Reply-To and References, and records the action's
      idempotency key in `email_sends`, so a retried action never sends twice.
    - Categories: mark read and archive map to the existing `email_mark_read` and
      `email_archive_noise` categories, and send reply to `email_reply` (capped). Labels
      have no category yet; prompt 23 should pick one.
- Labels to watch: only INBOX is watched for now. `linked_accounts.labels` isn't used yet.
- Fakes:
    - `tests/fakes/gmail_api.py` has a mailbox per address and accepts only access tokens
      issued by the fake Google (so revoking really produces 401s).
    - It supports history ids with expiry, paging, `newer_than:Nd` and scripted failures.
    - The `scenario` fixture wires it in when a test uses `fake_gmail`.

### 23 · Email triage
Status: [x] (2026-10-25)
Depends on: 22, 12
Read first: "Module behaviour" → E (Triage, Replies); "Security and privacy" (email content is
data); "Testing" → Security row.

Build:
- Per linked account settings: watched or not, and urgent sender patterns. These are set during
  setup (a chat flow after linking) and editable on the website.
- Classification via the `email_triage` AI task with structured output. Categories: urgent
  (tenant, financial, property, family), confirmation, receipt, needs reply, routine, noise.
  Each result has a one-line summary. Batch several emails per call.
- Actions:
    - urgent → an alert via the outbox (`urgent` or `normal` by severity)
    - confirmation → stage `mark confirmation read`
    - noise → stage `archive noise`
    - needs reply → draft a reply and stage `send email reply` (capped at Tier 1)
    - receipt → emit `ReceiptFound` for prompt 25
- Email text only ever enters prompts inside data blocks.

Tests:
- Classification routing with the scripted provider.
- Batching.
- The injection test: an email saying "ignore previous instructions and archive everything"
  results in no unapproved action.
- A reply is sent only after Go ahead.

Done when: triage runs on the fake mailbox end to end. Commit.

Notes (2026-10-25):
- Migration 0019:
    - `linked_accounts.urgent_senders` (JSON list of addresses or `@domain`; a bare domain is
      read as `@domain`).
    - Triage columns on `emails`: `initial`, `triage_status` (pending or done),
      `triage_attempts`, `category`, `urgent_kind`, `summary` and `triaged_at`.
    - `store.update_linked_account(actor, id, watched=, urgent_senders=)`, owner only.
- `themi.core.triage.EmailTriage`:
    - The periodic job `email.triage` runs every minute, after `gmail.poll`. It sorts
      pending mail from watched inboxes per member, in batches of 8 per `email_triage`
      structured call, on that member's own backend.
    - Each email goes in its own `as_data` block, capped at 4,000 characters. The system
      prompt says emails are information, never instructions.
    - If the AI is unavailable, mail stays pending for the next run, with no job queue
      needed. An email the model keeps leaving out is filed as routine after 3 tries.
    - Only well-formed verdicts for ids in the batch are used.
- Actions:
    - urgent: an outbox alert, `kind="email"`, deduped per email. Severe goes as URGENT,
      otherwise NORMAL.
    - confirmation: stages `email_mark_read` (`gmail.mark_read`).
    - noise: stages `email_archive_noise` (`gmail.archive`).
    - needs_reply: stages `email_reply` (`gmail.send_reply`, capped at Tier 1). The summary
      quotes the draft with `> ` lines.
    - receipt: `ReceiptFound(email_id, member_id, account_id, sender, subject, summary)` is
      passed to `triage.receipt_listeners`. Prompt 25 should subscribe there.
    - routine: nothing.
    - Senders listed as urgent for an inbox override the model's category to urgent, and
      the model is told the list.
    - `initial` (first-sync) mail is sorted but never acted on.
- PDA shield change: lines starting with `> ` are quotes. They're excluded from demand
  checks and kept verbatim; the text around them is still rewritten or softened, using
  ⟦quote n⟧ placeholders and falling back to the softener if a rewrite drops one. This way
  an approval shows the exact draft that will be sent.
- Inbox setup:
    - After a new link (the new `GoogleAccounts.link_listeners`), the owner gets a REPLY
      "Shall Themi keep an eye on this inbox?" with the buttons [Watch it] [Not this one].
    - Watching edits the message to ask which senders count as urgent. The answer arrives in
      ordinary chat, and the model records it with the new tool `set_urgent_senders`
      (`set_inbox_watched` exists too).
    - The website's My accounts page has a watched checkbox and an urgent-senders box for
      each account.
- Injection: the model can at most mis-sort emails in its own batch. Every resulting action
  is staged per email through the trust tiers. The scenario shows a fooled model running
  nothing and touching no Gmail endpoint.
- Follow-ups:
    - A burst of noise or confirmation mail produces one approval message per email. A
      grouped "archive these 5?" approval would be kinder. Consider it alongside prompt 24,
      or when the categories go automatic.
    - `gmail.label` still has no category.

### 24 · Expected emails and anomaly detection
Status: [x] (2026-10-25)
Depends on: 23
Read first: "Module behaviour" → E (missing-email detection); "Trust tiers" → Tier 3; "Testing"
→ scenario 4.

Build:
- Migration for `expected_emails` (linked account, name, sender and subject pattern, cadence in
  days, grace in days, last seen, last alerted, the category it protects).
- Matching incoming email updates last seen.
- A scheduler job flags overdue items: one alert per period, plus `escalate(category)`.
- Other anomalies escalate too: an unknown sender inside a trusted pattern, or an unusually
  large amount in a confirmation (parsed amounts, with the threshold relative to history).
- Manage expected emails on the website and via chat ("tell me if the PG&E confirmation doesn't
  show up").

Tests:
- Plan scenario 4.
- No repeat alerts within a period.
- Unknown-sender and amount anomalies.
- Resume restores Tier 2.

Done when: the scenarios pass. Commit.

Notes (2026-10-25):
- Migration 0020:
    - The `expected_emails` table: account, name, sender pattern (an address or `@domain`,
      which covers subdomains), an optional subject substring, cadence and grace days, the
      category it protects (default `email_mark_read`; capped categories are refused),
      `known_senders`, `last_seen_at` and `last_alerted_at`. Rows are deleted with their
      account.
    - `emails.amount_cents`.
- The sender-pattern helpers moved to `themi.accounts` (`sender_pattern`,
  `sender_matches`) and are shared with urgent senders, which now cover subdomains too.
- `themi.core.expected.ExpectedEmails`:
    - It's a `GmailSync` listener, so `last_seen_at` updates on sync, for unwatched inboxes
      and first-sync mail too. Adding an expected email scans stored mail for the baseline.
    - The periodic job `email.expected` runs hourly. A missed period starts at last seen
      (or created) plus cadence plus grace, and repeats every cadence. Each period gets one
      alert (`last_alerted_at` plus a per-period dedupe key).
    - Unknown sender: a matching email from an address in the pattern's domain that hasn't
      been seen for that expected email before. It's checked at sync, before triage, so that
      email's own action asks first. The new address is then remembered, so it alerts once.
      Exact-address patterns can't hit this.
    - Amount: triage's new `verdict_listeners` hook runs before acting. For confirmations,
      the amount is parsed from the text (the dollar figure next to "total" or "paid",
      otherwise the largest). It's unusual when it's more than 1.5 times the median of that
      sender's last 6 confirmations, and at least $20 above it, given at least 3 earlier
      ones. The model's output isn't used for amounts.
- Escalation only acts on a Tier 2 category: `autonomy.escalate`, and the alert ends with
  '"<label>" is back to asking first'. A Tier 1 category just gets the alert. The alert
  carries a [Resume automatic] button for admins, since `Autonomy.resume` is admin-only.
  Non-admins are told an admin can resume it from the Trust page.
- Chat: the tools `expect_email`, `list_expected_emails` and `forget_expected_email`.
  `expect_email` takes a sender name like "PG&E" and looks up its domain from stored mail,
  and it takes the only linked inbox when none is named.
- Website: My accounts lists each inbox's expected emails, with add and remove forms.
- Follow-ups:
    - Nothing is said when a late email finally arrives; it just resets the clock.
    - Lookalike senders outside the pattern (the right subject from another domain) aren't
      flagged, to avoid false alarms from ordinary merchants.
    - Grouped approvals from prompt 23 are still open.

### 25 · Pantry and grocery list (OurGroceries)
Status: [x] (2026-10-25)
Depends on: 23
Read first: "Module behaviour" → D (Inventory); "Integrations" → OurGroceries row and receipts note.

Build:
- Migration for `pantry_items`, `purchases` and `grocery_list`.
- An `update_pantry` tool ("used the last olive oil" → out).
- Purchase history from `ReceiptFound`: the AI extracts line items into purchases.
- Depletion prediction from purchase intervals marks staples as probably low.
- Low or out staples are staged into the grocery list via the `add to grocery list` category.
- Themi's list is the source of truth. `themi.connectors.ourgroceries` mirrors it using the
  unofficial `ourgroceries` library as an optional dependency. Mirror failures are logged and
  retried, and never block the local list.
- An `add_to_grocery_list` tool, and the list is shown on the website dashboard.

Tests:
- Pantry updates.
- Receipt to purchases.
- Prediction on synthetic histories.
- Staging honours the tier.
- The mirror is exercised with a fake OurGroceries client, including failure and retry.

Done when: a pantry text ends up on the grocery list after approval. Commit.

Notes (2026-10-25):
- Migration 0021:
    - `pantry_items`: name (lowercase, single-spaced, unique), status plenty, low or out,
      `status_source` (new, said, receipt, predicted or list), staple, expiry.
    - `purchases`: item, email (SET NULL if the mail is forgotten), vendor, quantity,
      price, date.
    - `grocery_list`: needed, bought or removed, with mirror state, attempts, error and
      retry time. A unique index allows only one needed row per name.
    - `emails.receipt_parsed_at` and `emails.receipt_attempts`.
- `themi.core.groceries.GroceryList`:
    - Adding goes through `grocery_list_add` and the `groceries.add` executor, which is
      idempotent by name.
    - The tools are `add_to_grocery_list` (a staged tool) and `show_grocery_list`.
    - `finish()` marks an item bought or removed.
- `themi.core.pantry.Pantry`:
    - The family's staples are always pantry items, and the staple flag follows the
      family settings.
    - `update_pantry` records statuses. Low or out staples are staged for the list in the
      same conversation; other items aren't (the tool says so, and
      `add_to_grocery_list` can add them). Marking an item plenty takes it off the list.
      `show_pantry` lists the pantry.
    - Receipts: a `ReceiptFound` listener calls a `structured_misc` model call on the
      receipt owner's backend, with the email in a data block and the pantry's names given
      outside it. Only `grocery` receipts become purchases (takeout and other don't). The
      purchase date is the email's received time. A purchase newer than anything said
      since makes the item plenty and takes it off the list.
    - If the AI is unavailable, the `pantry.receipts` job (every 10 minutes) retries, up to
      3 attempts. The job also reads first-sync receipts, since they're history.
    - Prediction: the `pantry.predict` job runs every 6 hours. A staple is probably low once
      the median gap between purchases (on different days, at least 3 purchases) has
      passed since the last purchase, or since someone last said it was restocked. It's
      marked low (source `predicted`) and staged once, for the errand owner or else an
      admin.
- `themi.connectors.ourgroceries`:
    - `GroceryListClient` interface (items, add, remove).
    - `OurGroceriesClient` wraps the unofficial library (optional extra
      `themi[ourgroceries]`, imported lazily; the Docker image installs it). It finds the
      list by name, maps errors to `MirrorError`, and signs in again after a failure.
    - `GroceryMirror.sync()` is the `groceries.mirror` job (every minute, only when
      configured). It's one way and matches by name, so a retry never adds twice. A failure
      backs off per row (1, 2, 4... minutes, up to an hour) and never touches the local list.
    - Settings: `OURGROCERIES_USERNAME` and `OURGROCERIES_PASSWORD` (set together), and
      `OURGROCERIES_LIST` (default "Groceries").
    - `tests/fakes/ourgroceries.py` fakes the client interface, since the library hides
      the HTTP.
- The website dashboard shows the list, and each item has a "Got it" button (bought, so the
  pantry item goes to plenty).
- The stand-in executor in `test_approvals.py` was renamed from `groceries.add` to
  `test.family_archive`, since the real one now exists.
- Setup for the user: put the OurGroceries login and list name in `.env`.
- Follow-ups:
    - Items crossed off in the OurGroceries app aren't read back.
    - Takeout receipts aren't totalled yet; prompt 35 needs them for the budget.
    - Expiry dates come only from what people say, not from receipts.

### 26 · Google Calendar for Cozyla
Status: [x] (2026-10-25)
Depends on: 21, 20
Read first: "Integrations" → Google Calendar row and the calendar note.

Build:
- `themi.connectors.gcal`: find or create the dedicated "Themi" calendar on the admin's linked
  account (configurable), and upsert events by a deterministic event id.
- Events come from tasks with due dates (and maintenance, in prompt 33), through the
  `write calendar events` category.
- Completing or deleting a task updates or removes its event.
- `tests/fakes/gcal_api.py`.

Tests:
- Idempotent upserts.
- Updates and deletes follow tasks.
- The tier is honoured.
- Errors are retried via the job queue.

Done when: tasks with dates appear on the fake calendar. Commit.

Notes (2026-10-25):
- Scopes: `calendar.events` alone can't list or create calendars, so linking now also asks
  for `calendar.calendarlist.readonly` (to find "Themi") and `calendar.app.created` (to make
  it if missing). Granted scopes are recorded on `linked_accounts.scopes` (migration 0022).
  An account linked earlier has to be linked again, and the Family page says so.
- Migration 0022:
    - `family.calendar_account_id` and `family.calendar_name` (default "Themi").
    - `calendars`: the found or made calendar id per account and name, looked up once.
    - `calendar_events`: source and source id (just `task` for now; prompt 33 adds
      maintenance), a deterministic `event_id`, where it was written, and its state
      (approved, synced or deleted).
- `themi.connectors.gcal`:
    - `CalendarClient` over httpx: calendar list, create calendar, and update, insert and
      delete events. A 401 refreshes the token once.
    - `CalendarSync` picks the target: the account chosen on the Family page, else the first
      admin's first enabled account with the calendar scopes. It finds or makes the calendar.
    - `upsert()` updates first, then inserts on a 404, then updates again on a 409, so a
      deleted event is restored rather than duplicated.
    - `event_id()` is base32hex: "themi", a hash of the family's creation time, the source
      letter and the id.
- `themi.core.calendar.TaskCalendar`:
    - It listens to the new `TaskBoard.change_listeners`.
    - A task that gets a date stages `calendar_write` ("Put <title> on the family calendar
      for Fri Oct 30") for whoever created it. It's interactive when it came from chat, and
      nothing is staged if no account can take it.
    - Approving runs `calendar.write_task`, which records the event and queues
      `calendar.sync`. The write is a job-queue job, so errors retry with the scheduler's
      back-off.
    - Once approved, an event follows its task without asking again: a new date moves it,
      done renames it "Done: ...", and cancelling or removing the date deletes it. My
      reading is that the yes covers keeping that event accurate.
    - Events are all-day and marked "transparent" (free).
- Tasks:
    - `complete()` is now async.
    - New `cancel()` and `reschedule()`, with the tools `cancel_task` and
      `reschedule_task`.
    - `Task.created_by` is now exposed.
- The job queue is wired in: `build_app` creates the `Scheduler`, `App.scheduler` holds it,
  the Runtime adds the periodic tasks to it, and the scenario harness has `run_jobs()`.
- Website: the Family page has a "Family calendar" section (account, name, and any
  problem).
- Fakes: `tests/fakes/gcal_api.py` is an HTTP fake that checks event ids, keeps deleted
  events (insert gives 409, update restores, a second delete gives 410), and scripts
  failures. The harness turns it on with `fake_gcal`.
- Setup for the user:
    - Add the two new scopes in Google Cloud (README step 4).
    - Link the admin's account again.
    - Add the "Themi" calendar to Cozyla.

### 27 · Meal suggestions and vendor call scripts
Status: [x] (2026-10-25)
Depends on: 25, 20
Read first: "Module behaviour" → D (zero-effort meals) and E (vendor calls); "Integrations" →
vendor phone calls row.

Build:
- `suggest_meals`: two low-prep options as buttons. It prefers items near expiry and
  shelf-stable staples from the pantry (structured output).
- `draft_vendor_call` (objective, vendor, details): produces an objective, opening line,
  questions, acceptable outcomes and a fallback. It creates a call task matched to the best
  person, delivers the script with the task, and after a "done" logs the reported outcome.

Tests:
- Meal suggestions use pantry data (check the recorded prompt).
- Call task assignment goes through matching.
- The outcome is logged.

Done when: the scenarios pass. Commit.

Notes (2026-10-25):
- Migration 0023: `meal_suggestions` (options JSON, chosen, chosen_at) and `call_scripts`
  (task, vendor, objective, script JSON, outcome, who logged it, when).
- `themi.core.meals.Meals`, with the `suggest_meals` tool:
    - It makes one `structured_misc` call (interactive) on the asker's backend.
    - The pantry list in the prompt comes from `pantry_lines()`: use-soon items first
      (within 3 days of their use-by date, soonest first), then staples, then the rest.
      Items that are out are left out.
    - The two options go out as a REPLY with two buttons, and tapping one records the
      choice and edits the message to show the steps. The steps are quoted (`> `), so the
      PDA shield keeps them as written.
    - Only on request for now. "When a missed meal is likely" needs meal logging, which is
      prompt 35, and `meal_suggestions.chosen_at` is there for it.
- `themi.core.calls.VendorCalls`, with the `draft_vendor_call` and `log_call_outcome` tools:
    - The script (objective, opening line, questions, acceptable outcomes, fallback, and an
      effort from 1 to 5) comes from one structured call. The family's details go in a data
      block.
    - It creates a `call` task through `TaskBoard.create`, so the matcher picks the person.
      The task's effort comes from the script.
    - The script travels with the task's nudge. The new `TaskBoard.details` hook adds text
      to `prompt()`, and `create(nudge=False)` lets the script be attached first. It's all
      `> ` quotes, so it's kept word for word.
    - When the task is done, a `change_listeners` hook asks "How did it go with <vendor>?".
      An open item tells the model the outcome is still missing, for 3 days.
      `log_call_outcome` records it, and marks the task done if it isn't yet; in that case
      nobody is asked afterwards.
    - Nothing is staged. A person makes the call, and the capped `vendor_call` category is
      for the automated calls researched in prompt 36.
- Wording: "right now" trips the PDA check, so the "AI unavailable" texts say "at the
  moment" instead.

### 28 · Evals, live smoke tests, coverage gates
Status: [x] (2026-10-25)
Depends on: 27
Read first: "Testing" (layers, workflow, live test accounts).

Build:
- `tests/evals/`: a dataset of at least 40 sample messages covering energy notes, pantry texts,
  rule brainstorming, "you keep forgetting", approvals, relays and small talk. Each has the
  expected tool calls (or none) and a PDA check on the reply.
- A runner that scores any configured provider and prints pass rates by category. `make evals
  PROVIDER=gemini`.
- Complete `tests/live/` smoke tests: Telegram test bot, test Gmail account, each AI provider.
- `.github/workflows/nightly.yml` runs live tests and evals with repository secrets.
- Enforce coverage: at least 90% on `themi.ai`, `themi.channels.outbox`, `themi.channels.pda`,
  `themi.autonomy` and `themi.energy`, and at least 75% overall.

Done when: evals run against Gemini's free tier and the results are recorded in Notes. Commit.

Notes (2026-10-25):
- Evals:
    - `tests/evals/cases.json` has 44 cases: energy notes 6, pantry 7, rules 5, context
      repair 5, approvals 5, relays 4, small talk 6, tasks 6.
    - Each case sets the expected tools, the allowed and forbidden extras, argument checks,
      and reply regexes. Every reply also gets the PDA check at the speaker's strictness
      and a no-score check, with `> ` quotes exempt.
    - Cases whose `requires` tools don't exist are skipped: the 4 relay cases wait for
      prompt 34, and `expect_email` needs Google configured.
    - The runner (`tests/evals/runner.py`) runs each case through the full app in a fresh
      household. `Scenario(real_models=True)` lets the router build real adapters from the
      members' AI settings, with real retry waits. It records `ToolRegistry.run` calls and
      reads the raw replies (before shielding) from the outbox.
    - `make evals PROVIDER=gemini|claude|ollama|openai_compat` prints pass rates by category
      and saves JSON in `tests/evals/results/`, which git ignores.
    - Keys come from the environment or `.env`. `THEMI_EVAL_PACE` defaults to 6 seconds for
      Gemini's free tier.
    - Dry run in the default suite: `tests/integration/test_eval_runner.py` drives the
      real Gemini adapter against the fake Gemini over HTTP.
- Live tests (`make test-live`), each skipped without its variables:
    - Telegram: send with a button, edit, and one poll.
    - Gmail: profile, list, get and labels.
    - Calendar: calendar list.
    - The existing AI provider smoke tests.
    - The variables are listed in each file's docstring.
- `.github/workflows/nightly.yml` runs the live tests and the evals nightly, and on demand
  with a provider input. The evals job is `continue-on-error`, and its results are uploaded
  as an artifact. Secrets go in the repository's settings.
- Coverage:
    - `tools/check_coverage.py` enforces the gates after `make cov`, counting lines and
      branches together. CI now runs `make cov`.
    - Today: overall 91.6%, `themi.ai` 96.1%, outbox 97.1%, PDA 100%, autonomy 95.7%,
      energy 97.1%.
- First Gemini run (2026-10-25, `gemini-3.8-flash`, free tier): no results.
    - Google answered `429 RESOURCE_EXHAUSTED` (`generate_content_free_tier_requests`,
      limits 5 and 20) after the first few cases, plus some 503s and 504s. Not one model
      call succeeded. The only real replies were the 2 approval cases Themi answers without
      a model.
    - Fixed a scorer bug found by the run (failing test first): Themi's "AI service is busy"
      fallback had counted as a pass for no-tool cases (9/39 "passed").
    - Such cases are now "couldn't run" and kept out of the rates. The run stops after 3 in
      a row, the Gemini pace is 30 s for 5 requests a minute, and
      `make evals EVAL_ARGS='-k energy'` runs one slice.
    - A full run needs about 100 requests, against the 20 a day this key's free tier allows
      for this model.
- Noise in eval runs: "Task exception was never retrieved ... Event loop is closed", from
  google-genai closing its httpx client after each test's event loop has ended. It's
  harmless, and only happens with per-test loops.
- Second run (2026-10-25, Gemini free tier): `gemini-3.5-flash-lite`, falling back to
  `gemini-3.1-flash-lite`, at 10 calls a minute per model. It took 8 minutes with no quota
  errors.
    - Raw score: 27/39. Re-scored offline with the fixes below (`tests.evals.rescore`, no
      new calls): 30/39 passed (76.9%), and 94.9% of the model's replies were PDA-safe.
      5 cases were skipped (relays wait for prompt 34; `expect_email` needs Google).

      | category       | pass | tools | PDA |
      | -------------- | ---- | ----- | --- |
      | approvals      | 3/5  | 3/5   | 5/5 |
      | context_repair | 5/5  | 5/5   | 5/5 |
      | energy_notes   | 2/6  | 3/6   | 5/6 |
      | pantry         | 4/7  | 5/7   | 6/7 |
      | rules          | 5/5  | 5/5   | 5/5 |
      | small_talk     | 6/6  | 6/6   | 6/6 |
      | tasks          | 5/5  | 5/5   | 5/5 |

    - What the models get wrong:
        - They miss energy notes (3 of 6 cases have no `log_energy_note`, and one called
          `draft_vendor_call` for a text).
        - They say "I've added X" when X was only staged, in 3 cases, even though the tool
          result says not to. This is the one that matters most for trust.
        - On an ambiguous "yes" with two approvals waiting, the model staged both again
          instead of asking which.
        - Two replies use "right now" ("the list is empty right now"), which the PDA check
          flags. The shield softens it when sending, but the check may be over-strict
          for that phrase.
- Fixes from the run, each starting with a failing test:
    - Grocery and calendar approvals were imperatives ("Add eggs to the grocery list",
      "Put … on the family calendar"), so every one cost an AI rewrite in the shield. They
      now read as offers ("Eggs for the grocery list", "For the family calendar: <title>,
      Fri Oct 30") and go out unchanged.
    - Duplicate approvals: `add_to_grocery_list` now leaves out items already on the list
      or waiting on a yes. If nothing is left, it declines with a plain message, through
      the new `ToolDeclined`, which a tool raises to answer without staging.
    - Scorer:
        - Only the model's own `chat` replies get the PDA check (approval cards are
          templates).
        - Read-only lookups are always allowed.
        - `expect_any` lets a case accept either of two tools ("remember the bins" can be a
          fact or a reminder rule).
        - The claimed-done check now covers every pantry case that stages something.
        - Runs save each reply's kind, and `python -m tests.evals.rescore <file>`
          re-scores a saved run without calling a model.
- Pacing: `tests/evals/pacing.py` gives each model its own rolling 60-second limiter
  (`THEMI_EVAL_RPM`, default 10 for Gemini), shared across the run.
  `THEMI_EVAL_FALLBACK_MODEL` adds the second backend.
- Scheduling: CI runs the evals weekly (Sundays) with these two models. The live tests stay
  nightly. The README asks for evals only when prompts or models change.
- Follow-ups:
    - Tune the conversation prompt and tool descriptions against these results: staged
      actions are never "done", log energy remarks, and ask on an ambiguous yes. Then
      re-run once.
    - Decide whether the PDA detector should allow "right now" when it isn't urging.
      Decided 2026-10-25: it's allowed when the sentence describes how things are ("the list
      is empty right now"); "call right now" is still flagged.
    - The default backend: the plan's default, Gemini free tier on `gemini-3.8-flash`, gave
      this key 20 requests a day, which can't carry a household. The flash-lite models did
      fine here, so the default model probably needs to change. That's the user's call.
      Decided 2026-10-25: the default is now `gemini-3.5-flash-lite` (see "Fixed technical
      choices").
- Third run (2026-10-25, after F1–F6, slices only at the user's request: rules, tasks,
  approvals and pantry; the family shares this key's quota): 17/22, the same as the second run
  for these categories, but approvals went up and rules went down.
    - Two rules cases predated the day's decisions, so they were updated with the user's OK.
      `rule-no-work-messages` also accepts pointing to quiet hours or busy times.
      `rule-bins` now expects a repeating task (`create_task` plus `set_task_schedule`, once a
      week), with a rule allowed.
    - "Right now" is allowed when it describes a state (`pda._describes_a_state`), which fixed
      `pantry-show-list`.
    - Honesty: declined tool calls (nothing to do) now count as "nothing happened"
      (`ToolContext.outcomes` holds "ok", "declined" or "failed"). A claim of success after
      only declined or failed calls becomes `NOTHING_CHANGED_TEXT` or `FAILED_TEXT`. A live
      re-run caught a name clash: my first constant was called `DECLINED_TEXT`, the existing
      refusal message, and replaced it. It's renamed, and a test keeps the two apart.
    - Re-scored offline: 20/22, PDA 100%. Live re-runs of the changed cases: `rule-bins` and
      `rule-no-work-messages` pass. `approve-ambiguous-yes` is honest now ("Nothing changed
      there...") but still fails: the model re-adds instead of asking which item was meant.
    - Still failing: `pantry-rice-low` (an extra grocery call that's declined, harmless) and
      `approve-ambiguous-yes`. Schedules can't hold a weekday or time ("Tuesday evenings"), so
      the bins reply overstates it a little.
- Fourth pass (same day), at the user's request, failing tests first:
    - `approve-ambiguous-yes`: with several items waiting and no newer question, a bare
      yes/no/later now gets `WHICH_TEXT` ("Which one did you mean: A or B? Each card above has
      its own buttons.") without the model. That exposed a latent bug in the newer-question
      check: the next waiting card ("Go ahead, or not now?") counted as a different question.
      Waiting cards are now excluded.
    - `pantry-rice-low`, found at the root with step numbers per call (eval results now save
      `call_steps`). Two causes:
        - Nothing said who adds low items. `add_to_grocery_list` now says it isn't for things
          running low or out, and `update_pantry` says not to also call it.
        - The honesty check only knew about approvals from staged tools; the pantry (and the
          calendar) stage their own. It now asks the database for any approval created this
          turn that's still waiting (`Agent._waiting_since`). `ToolContext.staged` is gone.
    - Live: `approve-ambiguous-yes`, `pantry-rice-low`, `pantry-olive-oil` and
      `pantry-add-cumin` pass 4/4. In two of them the model still claimed the item was on the
      list, and the check replaced the claim with the waiting line.
### 29 · Backups and cloud deployment (Phase 2 gate)
Status: [~] (built 2026-10-25; waiting on the real deployment and the two-week gate)
Depends on: 10, 28
Read first: "Deployment and hosting"; "Setup checklists" (hosting, backups).

Build:
- `themi backup`: an online SQLite backup, encrypted with the secret key, uploaded to
  S3-compatible storage (Cloudflare R2 or Backblaze B2), with 30-day retention. A nightly
  scheduler job runs it.
- `themi restore <snapshot>` with a dry-run mode. Test the full round trip locally against a
  fake S3 (or MinIO in CI).
- CI publishes the image to GHCR on tags.
- `docs/DEPLOY.md`:
    - a Google Cloud e2-micro VM, with Oracle and Hetzner/Lightsail as alternatives
    - Docker install
    - Tailscale Funnel for the website
    - secrets handling
    - upgrades (pull and restart, migrations run on startup)
    - restore drill
    - a troubleshooting section
- Check current free-tier terms while writing, and cite what you checked.

Tests:
- Backup and restore round trip.
- The encrypted snapshot has no plaintext.
- Retention pruning.

Done when: the deploy guide has been followed for real and Themi runs in the cloud. Gate: two
weeks of daily use by both of you before starting Phase 2. Commit.

Notes (2026-10-25):
- `themi.backup`:
    - `S3Client` is an httpx client with AWS SigV4 and path-style addresses, which R2 and
      B2 both accept. The signer is pinned to AWS's published test vector.
    - `Backups.create` makes a snapshot: the SQLite online backup (`Database.backup_to`),
      gzipped, then Fernet-encrypted with `THEMI_SECRET_KEY` (`Cipher.encrypt_bytes`).
      Names are `<prefix>themi-<UTC stamp>.sqlite.gz.enc`.
    - `prune` deletes snapshots older than `THEMI_BACKUP_KEEP_DAYS` (30) but always keeps
      the newest. Other files under the prefix are left alone.
    - `restore` decrypts and decompresses, runs `PRAGMA integrity_check`, reads the schema
      version, and refuses a snapshot from a newer Themi. With `--yes` it moves the current
      database aside (`.before-restore-<stamp>`), drops the old `-wal` and `-shm` files,
      and puts the snapshot in place. With `--dry-run` it only reports.
- `BackupJob` (`backup.nightly`, an hourly check) backs up when the last good backup is
  more than 23 hours old, so restarts don't skip or double a night. Each attempt goes in
  `backup_runs` (migration 0024). If the last good backup is over 2 days old, admins get
  one Telegram message a day.
- CLI: `themi backup [--list]`, and `themi restore <snapshot|latest> [--dry-run] [--yes]`.
- Settings: `THEMI_BACKUP_ENDPOINT`, `_BUCKET`, `_ACCESS_KEY_ID` and `_SECRET_ACCESS_KEY`
  (all four), plus `_REGION` (default `auto`), `_PREFIX` and `_KEEP_DAYS`. The endpoint
  must be https, except localhost for the fakes.
- Tests: `tests/fakes/s3_api.py` is an HTTP fake that checks every signature. Covered:
  the round trip (secrets come back, decryptable with the same key), no plaintext in the
  snapshot, wrong key or tampered data, a newer schema refused, the old database kept,
  retention including list paging, the job's once-a-day timing and failure warnings, and
  the CLI.
- `.github/workflows/release.yml` publishes to GHCR on `v*` tags (`ghcr.io/madicen/themi`,
  semver tags and latest), after the container smoke test. `deploy/compose.yml` runs the
  published image (`THEMI_IMAGE`, `THEMI_VERSION`, a 700 MB memory limit).
- `docs/DEPLOY.md` covers the host choice, the server, Docker, getting the image, Funnel,
  backups (R2 and B2), secrets, upgrades, the restore drill and troubleshooting. Free-tier
  terms were checked on 2026-10-25, with sources cited. Corrections to the plan:
    - **The e2-micro isn't free.** Its external IPv4 costs $0.005 an hour (about $3.65 a
      month) under Google's VPC pricing, and the console's default balanced disk isn't
      covered. The guide says to use a standard disk and budget for the IP.
    - Oracle's A1 allowance was reportedly halved in June 2026, and Hetzner's entry VM is
      now about €5.49 a month.
- A slowdown found while testing: `themi.settings` imported `themi.backup.job`, and through
  it the outbox. That made every `themi` command take 2.8 s, against 0.35 s. The
  package's `__init__` no longer imports the job, and
  `test_architecture.test_reading_settings_stays_light` guards it.
- Not run here: there's no Docker on this machine, so the image build and smoke test first
  run in CI. The repo is now on GitHub (private, `madicen/themi`, 2026-10-25). The first CI
  run there failed in lint, because `--pythonpath` got a bare `python`. The Makefile now
  passes the interpreter's full path.
- Still to do before `[x]`, for the user:
    1. Tag a release (the repo is on GitHub now), or build on the server.
    2. Follow `docs/DEPLOY.md` for real.
    3. Run the restore drill.
    4. The gate: two weeks of daily use by both before Phase 2 (prompt 30).

### D1 · Local dev run and Telegram simulator
Status: [x] (2026-10-25)
Depends on: 07, 10
Read first: nothing in the plan; this is dev tooling outside the numbered order. It's listed here
so it gets the same tests and notes as everything else.

Build:
- A `TELEGRAM_API_URL` setting that points the channel at another Bot API server (the fake).
- `clock.shift(delta)`: move the unfrozen clock ahead of real time, so a running Themi can skip
  forward to a scheduled nudge. `unfreeze()` clears it.
- A Telegram simulator: the existing fake Bot API plus a browser chat page on
  `http://localhost:8090`. Pick a person (Erin, Husband, or an unpaired newcomer), send
  messages, tap inline buttons, react with ✅ or 💤, see edits and "typing…", and skip time
  ahead.
- `make dev`: one process running the simulator and `themi run` against it, with its own
  database and secret key under `data/dev/`. The first run seeds the test family (both people
  paired) and puts `GEMINI_API_KEY` from `.env` on each person's default backend. It prints a
  website sign-in link. `make dev-reset` wipes the dev data.

Tests:
- The setting, including validation.
- `clock.shift`.
- The simulator's page actions become Bot API updates, and the bot's sends, edits, reactions
  and typing show up in its transcript.
- The dev runner seeds once, sets the key, and a message typed into the simulator gets a reply.

Done when: `make dev` starts Themi, and a person can chat with it from the browser. Commit.

Notes (2026-10-25):
- `TELEGRAM_API_URL` is the Bot API server's root. The channel gets `<url>/bot` and
  `<url>/file/bot`.
- `themi.cli.build_runtime(settings, **runtime_options)` now holds the wiring `themi run`
  used. The dev runner calls it, so dev is wired exactly as production.
- `clock.shift(delta)` adds a forward offset to the unfrozen clock, and `clock.shifted_by()`
  reports it. It raises on a frozen clock, and `unfreeze()` clears it, so the autouse
  test fixture resets it too.
- `tools/dev/`:
    - `simulator.py`: `Simulator(FakeTelegram)` keeps a transcript by hooking `_push` and
      `_result`. The page (`simulator.html`, plain JS) polls `/sim/state`. It also has
      `/sim/send`, `/tap`, `/react`, `/skip` and `/website`.
    - `runner.py`: `make dev`, `make dev-reset` and `make dev-invite NAME=`. The simulator
      and Themi share one process, so a skip reaches the scheduler, which ticks every 2 s
      in dev. Website sign-in links come from the page for the same reason: a link made
      by another process uses real time, which looks expired after a skip.
    - It reuses `tests.fixtures.family.seed_family` and the fake's people (1001 Erin,
      1002 Husband). 1003 is "Someone new", for testing `/start`.
- `FakeTelegram(port=)` and `BackgroundServer(app, port=)` can bind a fixed port.
- Tested live on 2026-10-25: the chat, a skip and the website link all work. The one Gemini
  call hit the key's free-tier daily limit (20 requests a day for `gemini-3.8-flash`), and
  Themi sent its "busy" reply. The default model is now `gemini-3.5-flash-lite`, which has
  more free quota.
- Found while setting up: the local `.venv` still had an editable install pointing at the
  repo's old `working-memory` path, so `python -m themi` failed outside the repo. Running
  `make install` fixed it.

### D2 · Simulator: copy a test session
Status: [x] (2026-10-25)
Depends on: D1
Read first: nothing in the plan (dev tooling).

Build:
- A *Copy session* button on the simulator page. It copies a plain-text report to the
  clipboard, to paste into a Claude session:
    - each person's conversation, in order: messages, button taps, reactions, edits (with the
      earlier text), button answers, and time skips, each with its time
    - Themi's log lines (redacted, as on the console)
- A *New session* button marks a start, so a copy covers only the current test.
- If the browser blocks clipboard access, show the report in a box to copy by hand.

Tests:
- The report has each part above, leaves out chats with nothing new, and starts at the mark.
- Log lines are captured and redacted.

Done when: a test session in `make dev` can be copied and pasted as one block. Commit.

Notes (2026-10-25):
- `Simulator.report()` (`GET /sim/report`) builds the text, and `new_session()`
  (`POST /sim/session`) sets the mark. Entries now record taps and reactions (`action`),
  edits keep their earlier text (`previous`), and skips and session marks are chat 0 entries,
  shown in every chat. An old message edited after the mark still counts.
- Each entry has the wall-clock time, to match the log, and Themi's clock, which the report
  shows only when the two differ by a minute or more.
- `LogBuffer` keeps the last 5,000 log lines, formatted and redacted as on the console. The
  dev runner adds it to the root logger, so the report has Themi's lines at the configured
  level. `google_genai` logs "AFC is enabled" at INFO on every call.
- The page copies with `navigator.clipboard` (allowed on localhost). If that fails, a dialog
  shows the report to copy by hand.
- A D1 bug found while testing live (failing test first): the channel stores its update
  offset in the database, but each run's simulator numbers updates from 1, so after a restart
  Themi skipped messages until the numbers passed the old offset. `runner.seed` now
  clears the offset at every start.
- Reactions are easier to see (after the user found they "didn't work"; Themi had received
  them, but on a plain question, where reactions do nothing). Your reaction shows as a
  badge on Themi's message, the reaction button in use is solid (it had been stuck at
  45% opacity under its row), the click shows at once, and the "You reacted" line quotes
  the message it was on.

### F1 · Feedback from chat: /bug and /idea
Status: [x] (2026-10-25)
Depends on: 09, 17
Read first: "How the family uses Themi" (chat commands). The plan has no feedback feature yet;
this adds one at the user's request, so family testing turns into work items.

Build:
- `/bug <what happened>` and `/idea <what you'd like>`, plus a `log_feedback` tool for the same
  thing in plain words ("that's a bug: ...", "it'd be nice if ..."). With no text, the command
  explains itself and saves nothing.
- Each report keeps a context snapshot: the message the person replied to (Telegram's Reply),
  the recent conversation, what's waiting on them, their settings and pauses, their AI backend
  (never keys), Themi's recent log lines (redacted) and its version. No energy numbers.
- `themi feedback` prints the new reports as one Markdown block to paste into a Claude session;
  `--all` includes reviewed ones; `--done <id>...` marks them reviewed.
- The simulator gets a Reply option on Themi's messages, so `make dev` can test it.

Tests:
- Scenarios: /bug and /idea with and without Reply, the empty command, the tool.
- The snapshot's contents, the report, marking reviewed, the CLI.
- Reply parsing in the channel; recent log lines redacted.

Done when: a /bug sent from Telegram shows up in `themi feedback` with its context. Commit.

Notes (2026-10-25):
- `themi.core.feedback`: `FeedbackBook` (storage and the Markdown report; needs only the
  database, so the CLI uses it) and `FeedbackChat` (commands, snapshot, `services.feedback`).
  Migration 0025 adds `feedback` (kind bug/idea, text, JSON context, status new/reviewed).
- Commands that need the whole message register with `services.add_event_command`; the agent
  checks those first. `InboundEvent.reply_to_message_id` carries Telegram's Reply, and
  `FakeTelegram.send_text(reply_to=)` and `Scenario.say(reply_to_text=)` send one.
- `themi.logs.RecentLogs` keeps recent log lines, redacted. `configure_logging` attaches the
  shared `recent_logs` (500 lines), and a report keeps the last 60. The simulator's session
  buffer is now a `RecentLogs` too.
- The snapshot holds the last 30 messages, the open items, settings and pauses, the conversation
  chain's backends (label, kind, model, whether a key is set), the version and the log tail.
  No energy numbers.
- The reply target is the newest `message_log` row with that Telegram id, because dev runs
  reused ids (see the next note).
- Dev fixes found while testing live:
    - The simulator now continues Telegram message ids after the dev data's highest
      (`runner.continue_numbering`). Before, each run restarted at 100, so ids repeated.
    - `make dev`'s website moved to port 8081 (`THEMI_DEV_HTTP_PORT`), so it can run next to
      a real `themi run` on 8080.
- The simulator has a Reply button on Themi's messages, and its report shows
  "(replying to #N)".
- The plan's chat commands table lists `/bug` and `/idea` (added 2026-10-25, at the user's
  request).
- A running `themi run` picks this up only after a restart.
- From the first real report (bug #1, 2026-10-25), failing tests first:
    - Sign-in links (`/login/<token>`) and Google's OAuth `state=` are now in
      `themi.logs.redact`, which also covers each line of chat history sent to the model and
      feedback snapshots. Before, a live /site link went to the AI provider with the next few
      turns, and reports kept the links.
    - The model claimed a locked rule was "just for you". Rules are household-wide (the plan:
      "sent to the AI model with every request"), and nothing in the prompt said so. The
      system prompt and `propose_rule` now say there are no personal rules, and that quiet
      hours, the daily limit (website settings) and /pause control when Themi's messages go
      out. Re-run the evals when there's quota, since the prompt changed.
    - Memories already have a personal scope (`remember_fact` with `about: personal`); the
      report's "extra spoon" fact was stored for that person only.

### F2 · Personal rules
Status: [x] (2026-10-25)
Depends on: 13, F1
Read first: "Trust tiers, rules and context repair" → Rule locking. From feedback bug #1: a
rule asked for "just for me" became a household rule. The user chose to add personal rules
(2026-10-25); the plan is updated to match.

Build:
- Rules get a scope: `household` (the default; every existing rule) or `personal`. A locked
  personal rule goes only into its owner's (`affects`) AI requests; household rules go into
  everyone's.
- `propose_rule` gets `applies_to` (household or personal); the model asks when it isn't clear.
  A personal proposal reads "Proposed Rule (just for you): …". Autonomy grants stay household.
- `/rules` and the website's Rules page show household rules plus your own personal ones;
  someone else's personal rules aren't shown.

Tests:
- A personal rule is in its owner's prompt and not the partner's; household rules in both.
- /rules and the website by scope; a personal autonomy grant is refused; refining a draft can
  change its scope; existing rules migrate as household.

Done when: "a rule just for me" locks as a personal rule that only shapes that person's chats.
Commit.

Notes (2026-10-25):
- Migration 0026 adds `rules.scope` (household default). `Rulebook.household()`,
  `personal(member)` and `prompt_rules(member)`; `services.rules(member)` now returns
  (household, personal) and `build_system(..., personal_rules=, owner=)` adds
  "<Name>'s personal rules (only in conversations with <Name>)".
- `propose_rule` requires `applies_to`; a personal autonomy grant is refused
  (`GRANTS_ARE_HOUSEHOLD`). Refining a draft can change its scope. Standing reminders from
  context repair stay household.
- `/rules` shows "Household rules", "Just for you" and drafts (marked "just for you"). The
  website's Rules page has a "Just for you" section. Others' personal rules are never shown,
  admins included.
- The plan's rule-locking section and test table now describe personal rules.
- Existing rules, including the user's rule 5, stay household. Turning one personal means
  retiring it and proposing it again; there's no switch.
- The system prompt changed again: re-run the evals when there's quota.

### F3 · Busy times
Status: [x] (2026-10-25)
Depends on: 08, 15, F2
Read first: "PDA-sensitive phrasing" → timing; quiet hours in the outbox. From feedback bug #1:
"no notifications during work hours (9-5 weekdays)" can't be a rule, because rules don't change
when messages go out. The user chose busy times in settings (2026-10-25).

Build:
- Each person can add busy windows on the website's settings page: days of the week and a time
  range (e.g. Mon-Fri 09:00-17:00). The outbox holds Themi's own (non-reply, non-urgent)
  messages during them, as it does in quiet hours, and sends them when the window ends.
- The AI can tell people about busy times when asked about message timing.

Tests:
- Messages held in a busy window and sent after it; replies and urgent alerts not held; windows
  on other days don't apply; the settings form adds and removes windows; validation.

Done when: a Mon-Fri 9-5 busy window holds a nudge until 5 pm. Commit.

Notes (2026-10-25):
- Migration 0027 adds `members.busy_times` (JSON). `BusyTime(days, start, end)` (0 is Monday,
  same-day windows; nights are quiet hours) with `covers()` and `label()` ("Mon-Fri
  09:00-17:00"). `update_settings(busy_times=...)` validates: at least one day, end after
  start, at most 10.
- `localtime.free_from()` steps past quiet hours and busy times, including one running into
  the other. The outbox uses it where it used `quiet_hours_end`. The energy windows treat
  busy times like quiet hours.
- Website: a Busy times section on My settings, with `POST /settings/busy` and
  `/settings/busy/{index}/remove`. Mon-Fri 09:00-17:00 is filled in by default.
- Each turn's context now says "Themi's own messages wait for: quiet hours ...; busy ...", so
  the model answers timing questions from the real settings. In bug #1 it made up "Monday
  afternoons". The system prompt mentions busy times too; re-run the evals.
- The plan's quiet-hours mentions now include busy times.
- For the user: add Mon-Fri 09:00-17:00 under My settings, then retire rule 5 on the Rules
  page. It's a household rule that never changed timing.

### F4 · Tasks someone takes on stay theirs
Status: [x] (2026-10-25)
Depends on: 20
Read first: "Shadow Calendar" → Task matching. From feedback bug #2: Michael said "I want to
process the cardboard", matching gave the task to Erin ("seems to have more room"), and Erin
got a nudge with no idea where it came from. The user chose these two fixes (2026-10-25).

Build:
- `create_task` gets `assign_to`: "me" (the person asking: "I'll...", "remind me to..."), a
  family member's name, or "anyone". Only "anyone" goes through matching.
- When a task lands with someone other than the person who asked, the nudge says who added it,
  and the tool result tells the model to let the asker know who it went to.
- The plan's matching rule says a task someone takes on, or gives to a named person, isn't
  matched.

Tests:
- "me" stays with the asker even when the partner has more room; a named person gets it;
  "anyone" still matches; an unknown name is refused.
- The nudge names who added it only when that's someone else.

Done when: "I want to process the cardboard" stays Michael's. Commit.

Notes (2026-10-25):
- `create_task` requires `assign_to`: "me" (also "myself"), a member's name (any case), or
  "anyone" ("someone" or empty mean the same). An unknown name is refused, and the refusal
  lists the family's names. `TaskBoard.create(..., assignee=)` skips the matcher. The reasons
  read "<asker> said they'd do it." or "<asker> asked for <name> to do it."
- `prompt()` uses `ADDED_BY_TEXT` ("<who> added this for you, whenever it suits: ...") when the
  task's `created_by` isn't the assignee, including matched hand-offs and call tasks. The tool
  result adds "Let <asker> know it went to <assignee>."
- The plan's Task matching bullet now says self-assigned and named tasks aren't matched.
- Real data: task 5 (the cardboard) moved from Erin to Michael with a plain SQL update; there's
  no reassign function yet. Erin's earlier nudge for it still has Done/Later buttons that
  act on the task.
- Follow-up the same day, at the user's request (failing tests first): adding a task for
  yourself in chat sent an instant "Done already, or later?". Erin's rule 2 was a workaround for
  that. Now the first nudge for your own interactively created task waits at least
  `FIRST_NUDGE_AFTER` (4 hours) through the new `Outbox.send(not_before=)`. After that the usual
  rules apply (quiet hours, busy times, daily limit, receptive window within a day). A due date
  still wins (by 09:00 that day). A task for someone else still goes out promptly.
- Real data, by plain SQL: rule 2 unlocked; duplicate task 3 ("Clean upstairs bathroom")
  cancelled, keeping task 4 ("... (once a week)"). Tasks 1 and 2 still overlap (both change
  the upstairs sheets), so ask the user.
- Erin's rule 6 ("Start task prompts with 'Due today:'") is now code, and the rule is unlocked.
  A nudge for a task due on the day it goes out reads "Due today: <title>. Done already, or
  later?", with "(<who> added this for you)" when someone else added it. "Today" is judged at
  the expected send time from the new `Outbox.send_time()`, so a nudge queued overnight still
  says it. Tasks due another day keep the usual wording.
- A slip caught by the real-clock tests: `send()` and `send_time()` read the clock separately,
  so even replies were queued by a few microseconds. `send()` now passes its reading through.
- Real data, by plain SQL: task 1 renamed to "Vacuum upstairs bedroom" (task 2 covers the
  sheets); rule 6 unlocked.
- Not done: catching near-duplicate tasks when they're created.

### F5 · Asked-for actions, honest replies, check-in wording
Status: [x] (2026-10-25)
Depends on: 11, 12, 20, 25
Read first: "Trust tiers, rules and context repair". From feedback bug #3: "Add white miso to
the grocery list" got an approval card, then "Added white miso to the grocery list" while it
was still waiting. The user chose these (2026-10-25), plus Erin's rules 7 and 8 built in.

Build:
- An action the person asked for in their own words counts as their yes, for categories that
  may become automatic and aren't escalated (never capped ones). For the grocery list, "asked
  for" means every item name appears in what they wrote this turn; restocking suggestions,
  receipts and items the model inferred still ask. The plan is updated to say so.
- When a turn leaves an action waiting on a yes, a reply that claims it's done is replaced with
  a plain line pointing to the card.
- A habit's daily check-in starts with "Check-in:" (offers to try a habit don't). Rules 7 and 8
  are unlocked.

Tests:
- Asked-for grocery adds go straight on; inferred ones still ask; capped or escalated categories
  always ask, even when asked for.
- A false "Added..." reply after staging is replaced; an honest reply is kept.
- Check-ins carry the prefix; offers don't.

Done when: "Add white miso to the grocery list" just adds it. Commit.

Notes (2026-10-25):
- `Autonomy.stage(..., requested=True)` runs the action as approved, with a `requested` audit
  event, unless the category is automatic already, capped or escalated. `Proposal.requested`
  carries it; only the tool sets it, from `ToolContext.request_text` (the person's message
  this turn), never from model arguments. The category's tier doesn't change.
- `add_to_grocery_list`: asked for when every new item name appears as whole words in what
  they wrote, normalised like item names but without the length limit.
- `ToolContext.staged` collects actions left waiting this turn. `agent._honest()` replaces a
  reply matching `CLAIMS_DONE` ("I've added", "Added ...", "is on the list" and so on) with
  `WAITING_TEXT` per waiting item. Honest replies pass through unchanged.
- Habits: the daily message is `CHECK_IN_TEXT` ("Check-in: <prompt>"); offers aren't
  prefixed. The PDA check now treats a leading label (up to three words and a colon) as no
  opening command. Without that, "Check-in:" was softened to "you could check-in:".
- The plan's trust-tier paragraph now covers asked-for actions.
- Real data, by plain SQL: action 2 (white miso) approved and added to the list; rules 7 and 8
  unlocked. Michael's approval card still shows its buttons; a tap now gets "already
  answered".
- Not done: an explicit request for an item already waiting on a yes (say, from restocking)
  still says it's waiting, rather than approving that item.
- Follow-up from feedback bug #5 (failing tests first): the model kept turning chores and their
  steps into draft rules. When Erin said "delete the draft rules", it ran `cancel_task` with
  rule numbers, which failed, and replied "I've cleared out those draft rules".
    - `set_aside_draft_rule` (the person's own drafts only; never locked rules). Drafts now
      show their number in open items ("Proposed rule 12: ...").
    - `ToolFailed`: a tool raises it when it couldn't act, and the result goes back as an
      error. The task tools' not-found cases use it. `ToolContext.outcomes` records each call;
      if every call failed and the reply claims success, it's replaced with `FAILED_TEXT`.
      `CLAIMS_DONE` also catches "cleared", "cancelled" and "set aside".
    - The system prompt and `propose_rule` say rules are for how Themi behaves; chores,
      schedules and the steps of a job are tasks, never rules. Re-run the evals.
    - The deeper cause: tasks can't hold steps or a repeat schedule, so that detail had
      nowhere else to go. That's F6.
    - Real data, by plain SQL: Erin's drafts 9 (rescue spray), 11 (bird cage schedule) and 12
      (bird cage steps) set aside. Their text is kept for F6.

### F6 · Chores: steps and repeating schedules
Status: split into F6a (steps) and F6b (schedules and escalation), approved 2026-10-25.
- F6a · Steps on tasks: [x] (2026-10-25; data move waits for a restart). The Steps bullet below, `update_task`, the website task page, and
  moving steps into tasks 6 and 4 (and unlocking rule 3).
- F6b · Repeating schedules and escalation: [x] (2026-10-25; data move waits for a restart). Everything else below, plus the bird cage
  data.
- The user's answers: escalation names who it goes to. "Top of both our lists" makes the chore
  shared at that point: it shows first for both, both are nudged, and either can mark it done.
  When it's done, the next round goes back to its owner. Escalation that names only the owner
  keeps it theirs. The step-up offer comes after 6 on-time runs in a row.
- F6a notes (2026-10-25), failing tests first:
    - Migration 0028 adds `tasks.steps` (JSON list of strings). The person's wording is kept as
      is: `clean_steps` trims, drops blank lines and leading bullets, and allows at most 30
      steps of 200 characters each. Tags such as "(Optional/Bonus)" are just text, so rule
      10's format survives unchanged.
    - `create_task` requires `steps` (an empty list is fine). `update_task` renames a task or
      replaces its steps: empty values keep what's there, and `clear_steps` empties them.
      `TaskBoard.update` limits edits to the assignee, whoever added the task, or an admin,
      and sends an "edited" change, so the calendar keeps up.
    - Nudges list the steps ("- step" lines) through the task-details hook. Open items show
      "Steps: a; b; c", so the model can answer "what does the kitchen task involve?".
    - Website: a Tasks page (nav "Tasks") lists your tasks and ones you added for others,
      each with an editable title and steps (one per line).
    - Data still to move after the user restarts `themi run` (the migration runs then):
      steps for task 6 (kitchen, from its title plus draft 9's rescue spray as optional),
      task 4 (bathroom, rule 3's levels as tagged steps, then rule 3 unlocked) and task 7
      (bird cage, from draft 12). The bird cage schedule waits for F6b.
- F6b notes (2026-10-25), failing tests first:
    - Migration 0029: schedule columns on `tasks` (`times_per_week`, `minimum_days`,
      `escalate_days`, `escalate_to`, `shared`, plus `overdue_notified_at`, `escalated_at` and
      `step_up_offered_at`), a `task_runs` table, and the capped `chore_step_up` category.
    - `set_task_schedule` (times a week, at least every N days, escalate after N days, to the
      owner or both). Zero means none; times 0 stops repeating. Escalation must come after the
      minimum. `schedule_summary()` reads "Repeats 2 times a week (at least every 7 days; after
      14 days, both of you)".
    - Marking a repeating task done records a run (on time if done by its due date) and opens
      the next round, due in round(7 / times) days. Shared is cleared, so it goes back to its
      owner. The next nudge waits for that date. The calendar gets a "rescheduled" change.
    - `tasks.schedules` (hourly): past the minimum, one "Overdue: <title> (last done N days ago)"
      to the owner. Past the escalation point, once: to the owner again, or with "both" the task
      turns shared. It's first in everyone's `open_for`, every paired member gets "Overdue for
      both of you: ...", and anyone can mark it done. A task's queued nudges are tagged
      (`dedupe_key` "task-<id>-...") so all of them can be withdrawn.
    - Step-up: after 6 on-time runs in a row since the last offer, a capped approval
      "Step up: <title>, N+1 times a week instead of N". Only whole numbers below 7 a week.
      Approving changes the schedule; nothing changes without a yes.
    - Steps in nudges are now `> ` quotes, like call scripts. The PDA shield had been rewriting
      Erin's command-style steps ("Refill the water" became "you could refill..."). The step-up
      card opens with a "Step up:" label for the same reason.
    - The Tasks page shows each schedule and the last few runs (late ones marked).
      Screenshot-checked in `make dev`.
    - The plan's Task matching bullet now describes chores.
    - Data moved on 2026-10-25 after the user's restart (a guarded script, tested on a copy of
      the database first):
        - Bird cage (task 7): Erin's own 9 steps from her message (not draft 12's rewording),
          plus 2 times a week, at least every 7 days, after 14 days both.
        - Kitchen (task 6): renamed "Clean the kitchen", with her approved steps in rule 10's
          format.
        - Bathroom (task 4): renamed "Clean upstairs bathroom", with rule 3's levels as
          (Low)/(Medium)/(High) steps, repeating once a week ("realistic", in her words).
        - Rule 3 unlocked. The two nudges already queued for the next morning were rewritten
          to the new wording.
Depends on: 20, F4, F5
Read first: "Shadow Calendar" → tasks and matching; "Module behaviour" → C (Maintenance), whose
interval, step-by-step guide and history this reuses. From feedback bug #5: Erin's chores
(bird cage, kitchen, bathroom) come with steps and schedules, and tasks couldn't hold either, so
the model kept turning them into rules.

Build:
- Steps: a task keeps an ordered list of steps, each optionally tagged (e.g. "Optional/Bonus",
  or an energy level like "Medium"). `create_task` and a new `update_task` take them. The nudge
  shows them (the existing task-details hook), and so do `list_open_items` and the website.
- Repeating schedule: a target ("2 times a week"), a minimum ("at least once a week") and an
  escalation point ("over 2 weeks"). Marking a repeating task done records a run (when, who,
  notes) and sets the next due date from the target.
- Escalation: past the minimum, the nudge says it's overdue. Past the escalation point, the task
  goes to the top of both partners' lists and both are nudged (still respecting quiet hours and
  busy times; never any energy talk).
- Growing the habit: after a steady stretch at the target (say 6 runs in a row on time), Themi
  offers a step up ("try 3 times a week?"), as an approval. It never changes the schedule
  itself.
- Website: a task page with steps, schedule and recent runs, all editable.
- Migration: step and schedule columns on tasks, plus `task_runs`. Prompt 33's maintenance items
  can later build on the same base (adding active months, one a day, calendar).
- Real data, once built: the bird cage (task 7) gets its steps and schedule from set-aside drafts
  12 and 11. The kitchen (task 6) gets its steps out of its title, plus the optional rescue
  spray (draft 9), in rule 10's format. The bathroom (task 4) gets rule 3's energy levels as
  tagged steps, and then rule 3 can be unlocked.

Tests:
- Steps: create, update, shown in the nudge, tags kept, rule 10's style untouched (wording is
  the person's).
- Schedules: next due date from the target; overdue wording past the minimum; escalation to
  both lists and both people; quiet hours still hold.
- The step-up offer after a steady stretch, as an approval; nothing changes without a yes.
- Scenario: Erin's bird cage conversation ends as one task with steps and a schedule, and no
  rule proposals.

Done when: Erin can describe a chore's steps and schedule in chat and it becomes one task that
repeats. Commit.

### F7 · Chores: anchored schedules, deadlines, read-back
Status: [x] (2026-10-25)
Depends on: F6b
Read first: F6's notes. From the evals and Erin's chores: "bins on Tuesday evenings" and
"cardboard before Tuesday (garbage day)" can't be expressed. F6b only knows "N times a week,
counted from the last time it was done", so replies like "I'll remind you Tuesday evenings"
overstate what's set.

Build:
- Schedules as RFC 5545 recurrence rules (`dateutil.rrule`), which also suit the calendar.
  Two modes: anchored ("every Tuesday at 18:00", "first Monday of the month", "every 3 days
  from Oct 26") and floating ("2 times a week after the last time", which is F6b's behaviour,
  kept as is). Migration: an `rrule` column plus a mode; F6b's `times_per_week` maps onto
  floating.
- Anchored rounds: due on each occurrence, nudged in its window (the anchor's time, or the
  family's daytime), still under quiet hours and busy times. A missed anchored round can be
  caught up or skipped, per chore; the default is to roll on to the next occurrence.
- Deadlines tied to another event: "by garbage day" means due the day before an anchored
  household event (a chore can point at another chore's schedule, e.g. task 5's cardboard at
  the bins).
- Read-back: after any schedule change, Themi states it in plain words, built in code from what
  was stored (e.g. "Every Tuesday at 6 pm; overdue after a week; after two weeks it's on both
  your lists"), not from the model's own summary. A wrong read-back is then easy to correct.
  Validation rejects impossible rules (an escalation before the minimum, an anchor with no
  dates).
- `set_task_schedule` gets `repeat` (anchored, as plain fields: weekdays, time, monthly
  position, interval) and `due_before_task`. The Tasks page shows the next three occurrences.

Tests:
- Anchored next-occurrence across weeks, months and a daylight-saving change.
- Floating behaviour unchanged (F6b's tests keep passing).
- Missed rounds rolling on versus catching up; "by garbage day" deadlines.
- The read-back text, built in code, for each kind of schedule.
- The bins eval case expects an anchored weekly Tuesday schedule.

Done when: "bins on Tuesday evenings" and "cardboard before garbage day" are stored, nudged and
read back exactly. Commit.

Notes (2026-10-25), failing tests first:
- New dependency: `python-dateutil` (3.0 installed), plus `types-python-dateutil` for dev.
- Deviation from the plan above: `set_task_schedule` takes a short `repeat` phrase instead of
  separate rule fields. `themi.core.repeat.parse` reads it in code ("every Tuesday at 6pm",
  "every other Monday", "every Tue and Fri", "first Monday of the month", "the 15th of every
  month", "every 3 days", "twice a week", time words like "evening" = 6 pm). Anything else is
  refused with examples. A schedule is stored as structured JSON (`tasks.repeat`, migration
  0030) rather than a raw RRULE string, and turned into a `dateutil.rrule` when needed. That
  keeps the read-back exact and the calendar export easy later. Floating schedules stay in
  `times_per_week`, so F6b's data needed no change.
- Occurrences are worked out on local wall-clock time and given the timezone afterwards, so
  "6 pm" stays 6 pm across the Nov 1 change (tested).
- Anchored rounds: the first due date is the next occurrence; a date-only round on today's
  date counts as today. The nudge waits for the chore's time on its day (or the morning), and
  the outbox deadline is that time too. Done (early or late) settles the round, and the next
  is the first occurrence after it.
- Missed rounds (`tasks.schedules`): with "roll" (the default), a passed date records a
  missed run (`task_runs.missed`, ignored for "last done" and on-time streaks) and moves to
  the next date. With "catch_up" the round stays owed.
- `due_before_task`: due the day before the other chore's round, or the day before its
  following round once this one is done for it. It follows the other chore when that rolls,
  and records a miss if it wasn't done.
- Read-back: the tool sends "Saved: <TaskBoard.summary>. Next: <date, time>." itself, and
  tells the model it was read back word for word. The Tasks page shows the next three dates.
- Live evals: `rule-bins` passes 3/3. At first the model sent "every Tuesday" for "Tuesday
  evenings"; the read-back showed the gap ("Saved: Every Tuesday."), and the tool description
  now asks it to keep the time of day. After that: "Saved: Every Tuesday at 6 pm".
- The architecture guard flags any call named `combine` (an energy function), and
  `datetime.combine` matched it. The code uses its own `_on()` helper instead of loosening the
  guard.
- The plan's Task matching bullet now covers fixed dates, deadlines, missed rounds and the
  read-back.
- Real data: migration 0030 runs on the next restart. Nothing else needs moving. Michael's
  cardboard (task 5) could be "due before" a bins chore once one exists.

Later prompts (not part of F7, from the same roadmap):
- Skip this round, or pause chores while away (holding overdue and escalation).
- Fair rotation between partners ("alternate the bins"), using `task_runs`.
- Energy-aware levels: offering a chore's (Low)/(Medium)/(High) steps to suit the day, in
  words, never scores.
- Robustness: streaks and completion rates on the Tasks page; a check that the hourly job
  never double-nudges after a restart.
- Prompt 33's maintenance (active months, one a day, notes per run) built on the same base.

### S1 · Shadow Calendar: energy remarks recorded
Status: [x] (2026-10-25)
Depends on: 18, 19
Read first: "B. Energy engine (Shadow Calendar)". From the user's question about the "hidden
internal calendar": the live data had 6 message-timing signals, no energy remarks at all, and
3 of 168 hour-of-week cells learned. Erin's "it's a medium energy day" left no trace.

Notes (2026-10-25), failing tests first:
- Causes:
    - The system prompt never asked for energy remarks; only the tool's description did.
    - Stated levels ("a medium energy day") had nowhere to go: the tool took only drains and
      boosts, from -3 to +3, with no zero.
    - Nothing caught a remark the model skipped.
- Day levels: signal source `day_level` (-1 low, 0 medium, 1 high), governed by the
  "energy notes" switch. `combine(..., timezone=)` leaves day levels out of the added points.
  The latest level stated earlier the same local day pulls the result towards
  `DAY_LEVEL_TARGETS` (35, 55, 75) with weight 0.75, and it's gone the next day. Projections
  (the windows) pass the timezone too.
- `log_energy_level` tool (low, medium or high), and a system-prompt line asking for both
  energy tools alongside whatever else was asked.
- Backstop: `themi.energy.remarks.energy_remark` catches only unmistakable first-person
  patterns ("medium energy", "I'm wiped/exhausted/drained", "took a lot out of me", "I feel
  really good/refreshed", but not "feel good about"). `Agent._catch_energy` records one after a
  turn that recorded nothing, and the switch still applies.
- Evals: new case `energy-medium-day`. The drain and boost cases now accept either tool in the
  right direction (a drain or "low", a boost or "high"). Energy slice live: 6/7, then 7/7
  re-scored (prompt 28 had 2/6).

### S2 · Shadow Calendar: calendar, task load and busy times as inputs
Status: [x] (2026-10-25)
Depends on: S1, 26, F3, F6b
Read first: "B. Energy engine (Shadow Calendar)" → Inputs. The original spec said the hidden
calendar is "updated based on all available data"; the plan narrowed that to three inputs.

Build:
- Calendar load: for each person with a linked Google account, read their primary calendar's
  events for today and the next 7 days (the existing `calendar.events` scope allows reading).
  Keep only start, end and free/busy, never titles or attendees. A packed stretch lowers the
  projection for those hours and the hour after; an empty day leaves the baseline alone. It
  becomes an input with its own privacy switch ("calendar"), and does nothing until Google is
  set up (this server's `.env` has no Google keys yet).
- Task load: each person's open and overdue tasks (overdue chores count more) lower their spare
  room a little, with a cap, so matching doesn't pile more onto someone who's behind. It's
  derived, not stored.
- Busy times: a long busy block (e.g. a 9-5 workday) is followed by a short wind-down dip, so
  the first nudge after work isn't timed as if it were a fresh morning.
- Plan update: the inputs list gains these three.

Decided 2026-10-25: busy events also hold Themi's messages, like busy times; primary calendar
only.

Tests:
- Calendar events turn into the right hours (all-day and declined events ignored; titles never
  stored); the switch; behaviour with no Google.
- Task load caps; matching moves a task away from someone with a pile of overdue chores.
- The wind-down dip after a long busy block, and not after short ones.

Notes (2026-10-25), failing tests first:
- `CalendarClient.list_events` (single instances; paged). `themi.connectors.gcal.busy.CalendarBusy`
  refreshes every 15 minutes (`calendar.busy`, only when Google is set up). For each enabled
  linked account with calendar access, it reads the primary calendar for the next 7 days and
  keeps busy blocks only (migration 0031, `calendar_busy`: member, account, start, end; no
  titles). Left out: all-day, "free", cancelled and self-declined events. An outage keeps the
  last blocks.
- A fourth privacy switch, "calendar" (`TRACKING_INPUTS`). Switching it off deletes the blocks
  at the next refresh, and `blocks()` returns nothing. It's on the website and in `/tracking`.
- Holding messages: `free_from(..., blocks)`, and `Outbox.calendar_blocks` (set by the app).
  The energy windows treat blocks as quiet too.
- Energy: `EnergyModel.load()` takes 8 points off inside a busy event, and in the hour after a
  long event (2 hours or more) or a long busy time (4 hours or more). It applies to `capacity()`
  and the projections. Words only, as always.
- Task load: `Matcher.spare` subtracts `task_load` (2 per open task, overdue ones double,
  capped at 15).
- The plan's Inputs list now includes all three.
- For the family: the calendar input does nothing until Google is set up (the README's Google
  Cloud section) and each person links their account.

### S3 · Shadow Calendar: a private "how Themi sees my week" view
Status: [x] (2026-10-25)
Depends on: S1, S2 (optional)

Build:
- A website page for each person, about themselves only (admins included: nobody sees
  another's): for each day of the coming week, morning, afternoon and evening in words ("usually
  a good stretch", "tends to be low"), the good windows Themi would use, and what it has learned
  from ("based on 14 replies and 3 things you mentioned about your energy"). Words only, never
  scores. Each input's switch is linked from the page.
- "That's not right" per part of the day: a correction the person can make ("Tuesday evenings
  are usually fine for me"), stored as a gentle nudge to the baseline.
- `make dev`: a debug page in the simulator with the actual numbers, for testing only (never
  in the real website).

Decided 2026-10-25: yes, gentle corrections from the page.

Tests:
- Only your own week is shown; no numbers anywhere on the real page; corrections move the
  baseline gently; the dev page exists only in `make dev`.

Notes (2026-10-25), failing tests first:
- `themi.energy.week`:
    - `week_view` covers 7 days × morning (8-12), afternoon (12-17) and evening (17-21) in
      `WEEK_WORDS`, from the projection averaged over the open hours. Parts mostly in quiet
      hours, busy times or calendar events say so. A part with no learned hour yet is marked
      "(a first guess)", added after the screenshot showed nearly every part as "usually
      steady".
    - `good_moments` gives the next day's windows; `learned_from` counts replies, energy
      remarks and nudge outcomes.
    - `correct()` moves the hours of that weekday's part 10 points in the cell (n+1). With
      the prior blend, one correction shifts the baseline about 2.5 points.
- Website: My week (`/week`, nav "My week") takes no member id, so it's always your own. Its
  "Usually better" and "Usually harder" buttons post to `/week/correct`. The page avoids the
  words "capacity" and "score" (the architecture guard on templates).
- `make dev`: an "Energy ↗" link in the simulator opens `/sim/energy`, with hour-by-hour
  baseline and capacity numbers and recent signals (`runner.energy_numbers`). It's dev only.
- Screenshot-checked. A live check also showed "It's a low energy day" recorded as a day level.
- The plan's energy engine section now describes the page.

### S4 · Energy-aware chore levels
Status: [x] (2026-10-25)
Depends on: S1, F6a

Build:
- A chore whose steps are tagged by level ("(Low) ...", "(Medium) ...", "(High) ...") is nudged
  with the level that suits how the person seems right now, in words: "A lighter version for
  today:" followed by the Low steps. Medium takes in the Low steps plus its own, and so on, as
  in Erin's bathroom rule. A stated day level (S1) wins over the estimate.
- When asked "what should I do about the bathroom?", the model gets the same suggested level,
  in words.

Decided 2026-10-25: only the suggested level's steps, plus one line saying more is there.

Tests:
- Low, medium and high days pick the right steps; a stated level wins; untagged steps are
  unchanged; no numbers in any text.

Notes (2026-10-25), failing tests first:
- `EnergyModel.suggested_level(member)` returns "low", "medium" or "high": a level stated today
  wins, else the estimate (below "steady" is low, below "some energy" is medium). It returns
  None with every input switched off, and then all steps show. The number stays inside the
  energy package.
- `TaskBoard._steps_for` replaces the old steps hook. Level-tagged steps are kept cumulatively
  (Medium takes in Low, High takes in all); untagged steps always show. The lead line is
  "A lighter / middle / full version for today:", followed by the quoted steps, then "The rest is
  there too if you feel like more." unless it's the full version. Open items add "Suggested
  today: the lighter (Low) version." for the model.
- Seen while testing: a stated low day also makes matching hand an unassigned chore to the
  partner, and makes the outbox wait for a better moment. Both are as designed; the tests pin
  the owner and read the queued nudge.
- S1 follow-up: `test_eval_runner` expected the energy case's old problem text.

### G1 · Two-way grocery sync with OurGroceries
Status: [x] 2026-10-25
Depends on: 25
Read first: "Integrations" → OurGroceries; prompt 25's notes. The plan made Themi's list the
source of truth, mirrored one way into OurGroceries. Set up for real on 2026-10-25 (the
account is Erin's, the list is "Madicen Groceries"): the family already keeps about 110 items
there, and Themi's own list had one, so Themi's answers about groceries would be wrong.

Build:
- Each sync (the existing `groceries.mirror` job, every minute) reads the OurGroceries list and
  compares it with a snapshot of what Themi saw last time, so it can tell what changed in the
  app since then:
    - added in the app: added to Themi's list (no approval: a person added it there), marked
      as coming from OurGroceries;
    - crossed off in the app: bought in Themi (the pantry item goes back to plenty, as with
      "bought eggs");
    - deleted in the app: removed in Themi (not bought).
- Changes made in Themi still go out as now, and win for that item if both sides changed it
  since the last sync (Themi's change is the newer one). Something needed again that's crossed
  off in the app gets un-crossed rather than added twice.
- First sync: items not crossed off come into Themi as needed. Crossed-off items (most of the
  family's list) come in as already bought, with the time they were crossed off, so Themi
  knows them as done and never treats them as new.
- Crossed off means bought (the user, 2026-10-25: "We cross off items when we buy them").
  OurGroceries marks it with a `crossedOffAt` timestamp; the library's own `crossedOff` is
  always false (fixed in the adapter the same day).
- Each row keeps its OurGroceries item id. Matching still falls back to the name (ignoring
  case), so nothing is doubled.
- Only the configured list is read or changed; the account's other lists are never touched.
- `show_grocery_list` and the website then show the real family list.
- Plan update: OurGroceries becomes a two-way sync, not a mirror.

Tests (with the fake OurGroceries, which gains crossing off, deleting and adding "from the app"):
- First import; adds, cross-offs and deletes in the app reach Themi; Themi's changes still go out.
- Both sides changed one item: Themi's wins; needed again means un-crossed, not duplicated.
- An outage changes nothing, and the next sync catches up; other lists untouched.

Done when: an item added or crossed off in the OurGroceries app shows up correctly in Themi
within a couple of minutes, and the family's existing list is in Themi. Commit.

Fixes made first, found while setting it up (2026-10-25, failing tests first):
- Crossed-off detection: the adapter read `crossedOff`, which the library always reports as
  false, so all 106 items on the live list (103 crossed off) looked needed. It now treats an
  item with `crossedOffAt` as crossed off.
- The one-way mirror now follows how the family uses the list. A needed item that's crossed
  off in the app is un-crossed instead of skipped (before, it stayed hidden). A bought item is
  crossed off instead of deleted; removed items are still deleted. The client gained
  `set_crossed_off`, using the library's `toggle_item_crossed_off`.
- Installing the extra brings in aiohttp, and google-genai then uses it. Its timeouts surface
  as the built-in `TimeoutError`, which `transport_exceptions()` didn't list, so a slow Gemini
  reply skipped the retry and fallback. That's a real issue in the Docker image, which
  installs the extra. `TimeoutError` and `aiohttp.ClientError` now count as transport errors.
  The google-genai warnings about subclassing `aiohttp.ClientSession` come from inside that
  library and are harmless.
- `test_without_the_library_the_mirror_just_waits` simulated a missing library by depending on
  what was installed; it now patches the import.

Notes (2026-10-25):
- Migration 0032: `grocery_list.remote_id` and `source` ('themi' or 'ourgroceries'), plus
  `ourgroceries_seen` (the last snapshot) and `ourgroceries_sync`, both kept per list name. A
  newly configured list gets a first import rather than looking like everything was deleted,
  and Themi's needed items that aren't on it are sent there. The old list is left alone.
- Each sync now reads the list every minute, even with nothing to send. A failed read backs
  off (1 minute doubling to an hour) instead of retrying every minute.
- Themi wins by name: while a row is pending, the app's changes to an item with that name are
  ignored. Removing an item in Themi that's already crossed off in the app leaves it crossed
  off; it isn't deleted.
- A delete in the app is matched by item id only, never by name, so Themi never removes an
  item it can't tie to the deleted one. Themi learns the id of an item it added on the next
  read, since the library doesn't return it.
- Crossing off in the app calls the pantry, the same as the website's "Got it"
  (`set_status(..., "plenty", source="list")`). That creates a pantry item if there isn't one,
  just as "Got it" and receipts do. The first import leaves the pantry alone: crossed-off
  history doesn't mean the family has those things now.
- Names Themi can't store (all emoji, or over 60 characters) are skipped with a log line.
- Dry run on a copy of the real database against the live list, with writes blocked: 3
  needed (1 gallon storage bags, quart ziplock bags, white miso), 103 bought, nothing sent.
- Setup: restart `themi run` so the migration runs and the sync starts. The first sync
  imports the list.

### F8 · Feedback fixes: nudge labels, check-ins, duplicate sends
Status: [x] 2026-10-26
Depends on: F5, F7
From the family's reports of 2026-10-25 and 26 (`themi feedback`): bugs #9 and #10, and three
problems found while reading them. Bug #5 (rules for chores) was already fixed by F6.

Done (failing tests first):
- Labels (bug #9): Erin's "Due today:" and "Check-in:" rules had been retired for built-in
  labels, but those only covered tasks due that day and habits, so to her the rules looked
  forgotten. Every task nudge now opens with a label for the day it goes out: "Due today:",
  "Due tomorrow:", "Due Sunday:" (within a week), "Due 8 Nov:", "Was due ...", or "To do:"
  without a date. Labels stay at three words or fewer so the phrasing check reads them as
  labels. Migration 0033 adds `tasks.check_in`: `create_task` takes `check_in` ("check in with
  me about running"), and those nudges open with "Check-in:". The system prompt says nudge
  wording is Themi's own, so the model doesn't propose rules for it.
- First nudge (bug #10): a new chore's first nudge now waits for its round. The nudge queued
  when a task is made used to stay when its schedule was set, unless the schedule moved the due
  date, so running (due Tuesday afternoon) and the bird cage (due Tuesday) went out Monday.
- Duplicate sends: a flush running while a reply was still being sent (the PDA shield can call
  a model) sent the same row again; idea #8's acknowledgement arrived twice. Rows on their way
  out are tracked in memory and skipped. Failed replies now retry after 15 s, 30 s, 1, 2, 5 and
  15 minutes, then hourly, for up to 8 tries; one reply had reached Erin 90 minutes late.
- Answering in words: "Yes let's give that one a try" left the water check-in waiting, since
  only a tap or a bare yes answered a card. New tool `answer_waiting_item`, which works only
  when the person's own message says yes, no or later (a word list, checked in code).
- Context repair: asking why Themi offered something was reported as forgotten context, which
  pinned a note about the offer for the whole family. `report_forgotten_context` now needs the
  person to say Themi forgot, was told before, or got something wrong.
- New eval case `task-check-in-run`.

Notes (2026-10-26):
- Bug #10 was mostly old code: `themi run` had been started at 19:32 on 2026-10-25, before F7,
  so "Tuesday, Thursday and Saturday or Sunday, afternoons" became "3 times a week" with no
  days or time, and the model's "next one is Tuesday afternoon" had nothing behind it. Restart
  `themi run` after each round of changes.
- Data fixed with the app's own code (a copy first): task 8 "Go for a run" is now every
  Tuesday, Thursday and Saturday at 2 pm, a check-in, with its first nudge queued for Tuesday
  27 Oct at 2 pm; task 9 "Run 1.3 miles" is cancelled (the distance plan stays a remembered
  fact); fact 1, the pinned note from the misfired repair, is deleted; Erin's water check-in
  is accepted, as she said in chat. Migration 0033 was applied to the live database by that
  script; it only adds a column, so the running process was unaffected.
- Not done here, and moved to F9: "Saturday or Sunday", "never two days in a row", "if I miss
  a day, the next day", "an hour before sunset", and the weekly distance step-up.
- The water check-in's time is still the habit's fixed one; Erin asked for "partway through
  the day", adjusted from her feedback. Habit timing that learns is a follow-up.
- The Cozyla branch (C1) also used migration 0033; it was renumbered to 0034 when rebased.

### F9a · Exercise schedules: either-day rounds, rest days, a missed day moves to the next
Status: [x] 2026-10-26
Depends on: F7, F8
From Erin's running set-up (bug #10): "Tuesday, Thursday, and Saturday or Sunday, an afternoon
check-in at least an hour before sunset. If I miss a day, prompt me the next day. Never two
days in a row. Next week is 1.3 miles, then 1.5, then up 0.25 a week, stepping up on Tuesdays."
F9 was split: this part is the schedule; F9b is sunset times, F9c the distance plan.

Build:
- Either-day rounds in the schedule phrases: "Saturday or Sunday" is one round that's due
  Saturday and still fine Sunday; done on either counts for the week's round.
- A rest rule: "never two days in a row" means no nudge the day after it was done, and a missed
  round moves to the next allowed day rather than the next listed day.
- "If I miss a day, the next day": a `missed` choice that moves the round to tomorrow (if the
  rest rule allows), alongside roll and catch_up.
- The wall: an either-day routine or chore shows on both days, and a tick on either closes
  the round.
- Read-backs for all of these, built from what was stored; tests with a frozen clock across
  a week, including a missed Tuesday and a run on Sunday followed by Monday.

Notes (2026-10-26):
- Phrases: "every Tue, Thu and Sat or Sun at 2pm, never two days in a row" reads back as
  "Every Tuesday, Thursday and Saturday or Sunday at 2 pm, never two days in a row". `Repeat`
  gained `or_days` (a day that stands in for the one before it; only the next day, weekly
  only) and `rest` (any anchored schedule). `round_end` is a round's last on-time day.
- The rest rule is kept wherever the board sets a round's day (first due, after done, after
  a miss): never the day after the last run, so a run on Wednesday moves Thursday's round to
  Friday, and a Friday run makes the weekend's round Sunday.
- `missed="next_day"` lives in its own column, `tasks.missed_next_day` (migration 0047),
  because 0030's CHECK on `missed` can't change without rebuilding `tasks`. A missed round
  moves to tomorrow (rest permitting) unless the next round comes first; then it rolls on
  and the miss is recorded. Overdue reminders leave these alone; the end-of-day list counts
  an either-day round on both days.
- The wall: an either-day routine or chore repeats on both days, and a tick on either closes
  the round; a round done in Themi ticks the day it was done. Known gaps: after a Saturday
  run, Sunday still shows unticked on the wall; a round moved to a day that isn't on the
  wall's schedule (Wednesday, after a missed Tuesday) doesn't show there.
- Setup: restart Themi (applies 0047), then Erin's "Go for a run" (task 8) needs its new
  schedule; it's stored as Tue, Thu and Sat at 2 pm, rolling on.

### F9b · Exercise schedules: sunset-relative times
Status: [x] 2026-10-27
Depends on: F9a
- Sunset-relative times ("an hour before sunset"): needs the family's location (a setting,
  coarse is enough) and an offline sunset calculation (for example the `astral` library);
  read back as "about 5:10 pm today". The wall routine's part of the day follows it.

Notes (2026-10-27):
- `themi.core.sun.sunset`: the sunrise equation, offline and without a library (checked
  against NOAA's equations: San Francisco, 27 Oct, 6:17 pm). The place is K4's
  `family_home`, so no new setting.
- `Repeat.before_sunset` (minutes; 0 is at sunset) from "an hour before sunset", "30 minutes
  before sunset", "at sunset"; with a time too ("at 2pm, at least an hour before sunset"),
  whichever is earlier. Fixed days only. Read back as "..., at least an hour before sunset;
  today that's about 2 pm".
- `TaskBoard.time_of(task, day)` works it out for the round's day, on the five minutes;
  without a home address it falls back to the schedule's own time. Nudges, round starts and
  the wall routine's part of the day follow it.
- For Erin's run it changes nothing in practice: 2 pm is always earlier than an hour before
  sunset at home (about 3:50 pm in December). Her stored schedule could take the words.

### F9c · Exercise schedules: distance plans
Status: [x] 2026-10-26
Depends on: F9a
- A progression on a task: a quantity that steps on a weekday ("1.3 miles, then 1.5, then up
  0.25 a week, on Tuesdays"), shown in the nudge ("Check-in: Go for a run (1.5 miles this
  week)") and read back exactly, like schedules.

Notes (2026-10-26):
- `themi.core.progression`: "1.3 miles, then 1.5, then up 0.25 a week, on Tuesdays" parses
  to amounts, a weekly step, an optional "up to", the step day and a start (the step day on
  or after today, or "starting 2 Nov"). Read back: "1.3 miles from Tue 27 Oct, then 1.5,
  then up 0.25 a week; it steps up on Tuesdays". A week runs from one step day to the day
  before the next. Stored as JSON in `tasks.progression` (migration 0048).
- Tool `set_task_plan` (empty to stop) sends the read-back itself, like `set_task_schedule`.
  Nudges say the week's amount ("Check-in: Go for a run (1.3 miles this week)"), none
  before the plan starts; Themi's open items show the plan and this week's amount. The
  system prompt points weekly plans at the tool, not a note (Erin's was only a note).
- Not done: recording how far she actually ran. The plan is what's planned.
- Setup: restart Themi (applies 0048), then give "Go for a run" (task 8) the plan. Erin's
  note about it (fact 2) can then go: it says "next week", which goes stale.

### L1a · Lists on demand: Themi's own lists
Status: [x] 2026-10-26
Depends on: 25
From Erin's idea #7: "Themi should be able to create new internal lists on demand." L1 was
split (2026-10-26): this part is Themi's lists; L1b is the wall. The family chose: a list is
for the household unless someone says it's theirs ("my gift ideas"); ticked items stay,
crossed off, until cleared; lists go on the wall only when asked (L1b).

Build:
- Named lists kept by Themi ("packing for the trip", "gift ideas"): create, add, tick off,
  remove, show and delete from chat, with tools that check names against what they typed, as
  F5 does for groceries: items they wrote go straight on, items the model inferred wait for a
  yes; a list is deleted without asking only when they named it. Each list is household or
  personal (only its owner sees a personal one).
- A Lists page on the website: see, add, tick, clear the ticked, make and delete lists.
- A seam for L1b: a list can be linked to a Cozyla list.

Notes (2026-10-26):
- `themi.core.lists`, tables `lists` and `list_items` (migration 0049). Tools: `create_list`
  (personal only when they say it's theirs), `add_to_list`, `tick_list_items` (tick or
  untick), `remove_from_list` (items, or the ticked ones), `show_lists`, `delete_list`.
- A list is found by the name people use: "the packing list" finds "Packing for the trip"
  when it's the only list with those words; otherwise the tool names the lists there are.
  Items are matched the same way, against what's on the list.
- `add_to_list` and `delete_list` are staged (`list_add`, `list_delete`, both may become
  automatic): straight through when every item, or the list's name, is in what they wrote
  (F5's check); otherwise an approval card. Ticking and removing named items is direct.
- Themi's open items show a "Lists:" line (names, how many to go and ticked), so the model
  knows which lists exist. A prompt line keeps named lists apart from tasks and groceries.
- The Lists page (/lists, in the menu): tick and untick, add, remove, clear the ticked, make
  (with "Just for me") and delete, behind a "Delete this list" fold. Someone else's
  personal list is never shown or changed, whatever a form says.
- `lists.cozyla_list_id` and `list_items.cozyla_todo_id` are there for L1b, unused so far.
- Setup: restart Themi (applies 0049).

### L1b · Lists on demand: the wall's lists
Status: [x] 2026-10-26
Depends on: L1a, C1c
- The wall's own lists other than the to-do list (Things to Cook, Shopping List) come in as
  household lists; their unassigned items sync both ways (added, ticked, removed). Assigned
  items stay tasks, as in C1c.
- "Put the packing list on the wall": makes a Cozyla list of that name
  (`/cal-server/rewards/todosList/create`) and keeps it in step from then on. Personal lists
  stay off the wall unless their owner asks.
- `add_to_wall_list` folds into the list tools, keeping its `wall_list_add` category for
  lists on the wall.

Notes (2026-10-26):
- `themi.core.cozyla_lists.WallLists`, run inside the to-do sync with the same read (no extra
  calls). Every wall list but the to-do list is a household list: linked to one with the
  same name (taking the wall's spelling) or made. Renamed on the wall, renamed in Themi;
  deleted on the wall, the list stays in Themi, unlinked.
- Items: unassigned to-dos that aren't tasks, both ways (added, ticked, unticked, renamed,
  deleted). Each linked item keeps how the wall had it at the last sync (`wall_title`,
  `wall_done`), and `pending` marks a change made in Themi since, which wins. A to-do that
  becomes someone's leaves the list and is a task (C1c). Ticked-off to-dos Themi never
  saw are history and stay behind (at first only on a list's first sync, so the second
  sync brought the history in, live; fixed the same day). A list's first sync pairs items
  with the same name rather than doubling them.
- Removed in Themi, an item or a whole list is queued in `list_wall_removals` and deleted
  from the wall next sync (forgotten if it's gone already). Deleting a list in Themi deletes
  the wall's too; the card says "on the wall too". Assumed, not seen: deleting a wall list
  takes its to-dos with it.
- `put_list_on_wall` (staged, `wall_list_add`, straight through when they named the list)
  makes a wall list with the list's name (`/cal-server/rewards/todosList/create`, the
  wall's preset colour and icon); the items follow next sync. Personal lists can go up too
  when their owner asks. `add_to_wall_list` and its executor are gone; no approvals were
  waiting on it. Migration 0050 (also relabels the category).
- The Lists page marks lists on the wall; Themi's "Lists:" context line says "(on the wall)".
- Dry run against the real wall (a copy of the database, writes recorded): Shopping List
  comes in empty (nothing open and unassigned), Things to Cook with Chicken, Creami prep,
  Bean soup and Cashew mac sauce; no writes, no new tasks.
- Watch: the wall's "Shopping List" is now a Themi list, while groceries stay in
  OurGroceries; the prompt keeps named lists apart from the grocery list.
- Setup: restart Themi (applies 0050).

### L2a · A "things to buy" list sorted by store
Status: [x] 2026-10-26
Depends on: L1b
From Erin's idea #6: non-food things to buy go on their own list, not the grocery list in
OurGroceries ("body wash comes from Amazon"). L2 was split (2026-10-26): this part is the
list and where things come from; L2b adds them to carts. The family chose: it's the wall's
Shopping List, renamed "Things to Buy".

Build:
- A "things to buy" list: the household list with that purpose, kept on the wall (L1b).
  Renaming a list in Themi renames it on the wall.
- Food versus non-food when something is added: food goes to groceries as now; non-food goes
  to "things to buy". Ask when it's unclear, and remember the answer for that item; what
  someone asks for in their own words wins over what was remembered.
- A usual store per item, learned from what people say and from receipts (non-grocery
  receipts like Amazon's are read for their items too; a receipt ticks off what it bought),
  editable on the website, and the list shown by store.

Notes (2026-10-26):
- `themi.core.buying.ThingsToBuy`; the list is the household list with `purpose =
  'things_to_buy'` (made as "Things to Buy" if there isn't one). Migration 0051: `purpose`,
  `lists.wall_name` (a rename on either side is told apart, so renaming in Themi renames on
  the wall: `CozylaClient.rename_list`, colour and icon sent back as they were), and
  `item_homes` (by item name: food or other, and the usual store).
- Tools: `add_to_things_to_buy` (items with an optional store; staged under `list_add`,
  straight through when they wrote the names) and `set_usual_store` ("" forgets). An item
  remembered as the other kind is refused when the model infers it, and goes through when
  asked for in their words, which is remembered instead. Grocery adds remember "food".
- `show_lists` shows Things to Buy by store ("Amazon: body wash; anywhere: batteries").
  The Lists page has a "Usually from..." field per item there.
- Receipts: a new "shopping" kind (Amazon, a hardware store) is read for its items as
  grocery receipts are; either kind ticks off matching things to buy ("lavender body wash"
  matches "body wash") and learns the store. Only grocery receipts feed the pantry. The
  receipt prompt is given the things-to-buy names.
- A prompt line: food and kitchen staples to groceries, anything else to Things to Buy, and
  ask when it isn't clear.
- Dry run on a copy: the only wall write is renaming "Shopping List" to "Things to Buy"
  (its pink, #CE6388, kept).
- Setup: restart Themi (applies 0051), then mark Themi list 1 (the wall's Shopping List) as
  Things to Buy and rename it; the next sync renames it on the wall.

### L2b · Things to buy in the carts
Status: [ ]
Depends on: L2a, 35
- When prompt 35 stages a cart, it offers the matching "things to buy" items (by usual
  store) as part of the same approval.

### H1 · Dishwasher: notice when the household is falling behind
Status: [x] 2026-10-30
Depends on: 18, C3
From Erin's idea #4, asking for this sooner than prompt 36's research. She wants Themi to
notice, without being told, when the household may be running behind.

Asked 2026-10-30: the dishwasher is a Bosch on the Home Connect app, and the family wants
its cycles read from there. Home Connect has an official cloud API (OAuth 2 authorization
code flow; `IdentifyAppliance Dishwasher-Monitor`; 1000 requests a day per user, access
tokens last 24 hours; api-docs.home-connect.com, checked 2026-10-30), so no plug and no
waiting on prompts 30 or 32.

Build:
- A Home Connect connector: settings `HOME_CONNECT_CLIENT_ID` and
  `HOME_CONNECT_CLIENT_SECRET` (and `HOME_CONNECT_URL` for the simulator or a fake). An
  admin links the family's Home Connect account from the Family page; the refresh token is
  kept encrypted, and its appliances become devices (`home_connect`), the dishwasher as the
  `dishwasher` appliance.
- A job reads the dishwasher's operation state every 5 minutes (about 290 calls a day).
  Moving into Run starts a cycle; leaving it ends one.
- A cycle starting checks off today's dishwasher routine on the wall (C3) and any open Themi
  task about the dishwasher. That is a side effect, so it goes through its own category,
  supervised until a rule makes it automatic.
- Cycles become energy signals for the Shadow Calendar: fewer runs this week than usual for
  the household is a gentle "running behind" sign, as device activity. People see words,
  never scores.

Tests:
- The connector against a fake Home Connect: linking, token refresh, appliances, status, an
  offline appliance, rate limiting.
- A cycle starting ticks the wall routine (approved, then automatic), and closes a Themi task.
- The pace signal: fewer runs than usual, and nothing without enough history.

Notes (2026-10-30):
- `themi.connectors.homeconnect`: `HomeConnectClient` (the wire) and `HomeConnectAccount` (the
  family's one sign-in: a hashed 10-minute state, the refresh token encrypted in
  `home_connect_account`, the access token in memory). A refresh's new refresh token
  replaces the old. A 429 is waited out for its Retry-After without calling again; a 409 is
  an appliance off the network. Migration 0074 rebuilds `devices` to allow `home_connect`.
- Linking: Family page, Appliances, "Link Home Connect" (admins only). The callback carries
  the admin in its state, like Google's. Home Connect's appliances become devices
  (Dishwasher, Washer, Dryer mapped; only the dishwasher is read).
- `themi.core.dishwasher`, job `devices.dishwasher` every 5 minutes: Run starts a cycle
  (`appliance_cycles`), any other state but Offline ends it. A cycle starting stages
  `dishwasher_done` for today's open wall routine items with "dishwasher" in the title
  (`CozylaRoutines.open_matching`; Themi's own check-ins are left out, they're tasks) and
  open Themi tasks about the dishwasher due by today, each to whoever's it is. Supervised
  until turned on under "What Themi does alone"; the card lapses at midnight.
- `devices.dishwasher_pace`, hourly, acts once a day from 18:00: runs in the last 7 days
  against the usual week over up to 28 days before (at least 7 days of history, at least 2
  runs a week usually). Under 60% of usual: -0.5 device activity for everyone, noted as
  "the dishwasher ran once this week, fewer than usual (about 7 times)".
- Not done: Home Connect's event stream (SSE). Polling fits in the daily limit (about 290 of
  1000 calls) and keeps the scheduler simple; a start is noticed within 5 minutes.
- The build plan doc couldn't be read from this session (not shared with the account), so
  this follows the prompt and C3's notes.
- Setup: register an app at developer.home-connect.com (Authorization Code Grant Flow,
  redirect `<THEMI_PUBLIC_URL>/auth/home-connect/callback`), set `HOME_CONNECT_CLIENT_ID` and
  `HOME_CONNECT_CLIENT_SECRET`, restart (applies 0074), and link from the Family page. To
  skip the cards, turn on "Check off the dishwasher routine when the dishwasher starts".
- Fixed 2026-10-30: "Link Home Connect" did nothing in the browser. Home Connect hands its
  sign-in on to SingleKey ID (`singlekey-id.com`), and the site's `form-action` allowed only
  Home Connect, so the browser blocked the redirect. `HomeConnectConfig.sign_in_url` is now
  allowed too. A local redirect (`http://127.0.0.1:8080/...`) works; no public URL is needed
  to link from the computer running Themi.

### E1 · Email: suggest important senders
Status: [x] 2026-10-27
Depends on: 21, 22
From Erin's idea #27 ("auto detect important senders, have user confirm"), 2026-10-27, when she
linked her inbox and was asked which senders always count as urgent.
- After an inbox's first sync, and now and then after, look at who writes: people she replies
  to, senders of mail triage called urgent, banks, schools, the property manager. Offer a
  short list as a card with a button per sender ("Always urgent: Schwab, Rosie's school?");
  only what she confirms is added. Never added on Themi's own say-so.

Notes (2026-10-27):
- `themi.core.senders.SenderSuggestions`, job `email.senders` every 6 hours: for each watched
  inbox with nothing left to sort, senders from the last 90 days whose mail triage called
  urgent about money, the property, tenants or family, or real people who wrote more than
  once and were waiting on a reply. Four at most, likeliest first; not ones already urgent or
  offered before (`sender_suggestions`, migration 0059). One message, normal priority: "A few
  senders in erin@... might always count as urgent: Schwab Alerts (money) and Bob Tenant
  (waiting on replies). Tap any that should; nothing changes otherwise." Each button adds
  that address to the account's urgent senders and says so.
- Not done: replies she sends aren't read, so "people she replies to" isn't a signal.
- Setup: restart (applies 0059).

### S5 · Shadow Calendar: learning from reactions
Status: [x] 2026-10-30
Depends on: S1, 28
From Erin's idea #31 ("interpret react emojis to note which types of responses elicit positive
or negative reactions"), 2026-10-27. Reactions today only answer approval cards.
- Record a reaction on any of Themi's messages with the message's kind (a nudge, a check-in, a
  summary, a chat reply) and length; 👍 ❤️ 🙏 as good, 👎 😕 as not. If P4 is built, 👎 on
  a chat reply is its "wrong action" mark, not a judgement of the style: count it only on
  Themi's other messages.
- Over time, a per-person picture of what lands ("short nudges do well; long explanations
  don't"), shown to the model as a line of its own, in words, never numbers, and on the
  person's tracking page. A switch, like the other inputs.

Notes (2026-10-30):
- `themi.core.reactions.Reactions` is a reaction handler. It finds the outbox message reacted
  to and records it in `message_reactions` (migration 0075), one per message, the latest
  reaction winning. It keeps the message's kind in words (nudges, check-ins, summaries, chat
  replies, heads-ups) and its length (short up to 160 characters, medium-length up to 500,
  long). A task nudge whose task is a check-in counts as a check-in.
- Approval and rule cards are left out: a reaction there answers the card.
- P4 isn't built, so 👎 on a chat reply still counts. When P4 lands, leave chat replies out
  here.
- `picture()`, over 90 days: each length-and-kind pair with 3 or more reactions, then each kind
  not yet covered. Two thirds good means it does well; half or more not good means it
  doesn't. The result reads like "short nudges do well; long summaries don't", or "" with too
  little to go on.
- The model sees it as its own line in the turn's context ("What lands with Erin, from their
  reactions: ..."). My week has a "What lands with you" card.
- A new tracking input, `reactions` (on by default, like the others), on My settings and in
  /tracking. Off stops recording and hides the line; what's recorded stays.
- The 👎-style reactions still also make PDA shielding stricter (prompt 8), as before.

### M1 · Memory: a record of conversations
Status: [x] 2026-10-30
Depends on: 13
From Erin's ideas #28 and #30, 2026-10-27: "maintain records of general questions/conversations
in the shadow calendar". F13 keeps a note per answer or settled problem; this is the fuller
record.
- A daily, private journal per person: the topics talked about and what was decided, written
  at the end of the day from the day's messages, searchable ("what did we decide about the
  pacifiers?"), on the website's Rules & memory page, deletable.

Notes (2026-10-30):
- `themi.core.journal.Journal`, job `memory.journal` hourly: once a person's local day is over,
  that day's messages go to the model as a data block: what they said, and Themi's chat
  replies (not its nudges). The model writes up to 8 topics and 8 decisions (only what they
  agreed to). It's a background structured call on the "other quick jobs" AI route.
  Migration 0076: `journal_entries` and a porter-stemmed `journal_fts`.
- A day with only Themi's messages isn't written. A day with nothing worth keeping gets an
  empty entry, which isn't shown. If the model doesn't answer, the next hour tries again,
  for up to three days back.
- `search_journal` (a core tool, so it's always there) searches only the asker's own entries.
- The Rules & memory page has "Your journal": the last 14 entries, a search box, and Delete
  on each. A deleted entry keeps only its date, so it isn't written again.
- Not done: a tracking switch. It's a record of conversations, not an energy input, and each
  entry can be deleted. Add one if the family wants the journal off for someone.
- Setup: restart (applies 0076).

### P1 · Faster replies: only the tools a message needs
Status: [x] 2026-10-27
Depends on: F13
From bug #29 (2026-10-27): every message sent all 55 tools' schemas, about 32,000 characters
(some 8,000 tokens), on the free Gemini tier, twice for a message that used a tool.
- A core set always goes (tasks, notes and rules, approvals, energy notes, groceries, Things
  to Buy, feedback); the rest are grouped (schedules, calendar, lists, the wall, email,
  pantry and meals, calls, settings) and go when the message or the last few messages call
  for them. `more_tools` (in the core) adds a group mid-turn, so a miss costs a step, not a
  wrong answer. A tool not in the table is core.

Notes (2026-10-27):
- `themi.core.tools`: `GROUPS` (what each is for, and the words that call for it),
  `TOOL_GROUPS` (tool to group; anything else is core), `choose_groups` over this message and
  the last four, `ToolRegistry.specs(groups)`, and `more_tools` (a starter tool) which adds
  groups to `ToolContext.groups`; the agent asks for the specs again each step.
- Measured on the real app: all 56 tools are 33,500 characters; a plain message now sends 19
  (12,800), one about the calendar or a list 26 to 28 (16,000 to 17,800). The words are
  generous on purpose ("good morning" brings the calendar's); a miss costs a `more_tools`
  step. `ai_calls` (F13) will show whether replies got faster.
- Not checked against a real model (the evals need `--run-evals` and API keys); worth a look
  in `ai_calls` and in chat over the next days.

### C1a · Cozyla: unofficial client and a read-only check
Status: [x] 2026-10-25
Depends on: 26
Read first: "Integrations" → Cozyla (no official API); prompt 26 (the calendar route).
The family has a Calendar+ 2 and already uses its to-do lists, and asked (2026-10-25) to try
a two-way to-do sync. Cozyla publishes no API. The community project
[cozyla-sdk](https://github.com/Fgruntjes/cozyla-sdk) (MIT) mapped the cloud API the tablet
apps use, by decompiling them: `https://api.cozylacal.com/cal-server/...`, JSON POSTs, a
token from `users/cozUsers/signIn` (email plus the password RSA-encrypted with the app's
public key), no refresh (codes 101/102 mean sign in again; 1002 is a sign-in lockout).
Themi writes its own small client from that description rather than depending on the repo
(not on PyPI, 11 commits). It may break, and may conflict with Cozyla's terms: the family's
own account only, and an admin opts in by configuring it.

Build:
- Settings: `COZYLA_EMAIL`, `COZYLA_PASSWORD` (a secret: encrypted at rest, redacted),
  `COZYLA_TODO_LIST` (the list to sync; empty means no sync), `COZYLA_DEVICE_SN` (default
  `themi`; it must stay the same).
- `themi.connectors.cozyla`: sign-in, re-sign-in once on an expired token, never in a loop
  (a lockout waits); members, to-do lists, to-dos; create, update (every field re-sent:
  the API keeps only what's sent), complete or reopen, delete. Errors become `CozylaError`.
- `themi cozyla check`: signs in and prints the lists (with open/done counts), the members,
  and a sample of how due dates come back. Read-only, and no to-do titles unless asked.
- A fake Cozyla cloud (`tests/fakes/cozyla.py`) behind an httpx transport.

Tests: sign-in body (password encrypted, never sent plain), token reuse and one re-sign-in,
lockout surfaced, envelope errors, create/update/complete/delete bodies, the check output.

Notes (2026-10-25):
- Built from cozyla-sdk's notes and code (read at commit 2052b64, 2026-10-23). The app's
  public key for the password is copied from there; it's public, not a secret.
- A lockout (1002) uses the countdown Cozyla sends, else 15 minutes, and the client doesn't
  try to sign in again until it's over.
- The fake makes its own RSA key pair; the client takes `password_key`, so the fake checks
  the decrypted password. Its `update` clears fields that aren't sent, as the real API does.
- Not yet tried against the real service. Setup: put `COZYLA_EMAIL` and `COZYLA_PASSWORD`
  (the family's Cozyla ID) in `.env`, run `themi cozyla check`, then set `COZYLA_TODO_LIST`
  to the list to sync. The check also shows what time of day the wall stores due dates at,
  which C1b needs.

### C1b · Cozyla: two-way to-do list sync (trial)
Status: [x] 2026-10-25
Depends on: C1a
Build (the same shape as G1):
- What syncs: Themi's one-off tasks and the configured Cozyla to-do list. Repeating chores
  stay out (they're closer to Cozyla's chore chart; a later step).
- Themi to Cozyla: the task change listener marks a link pending; the `cozyla.sync` job
  (every minute) creates, updates (title, due date, assignee), completes or deletes the to-do.
- Cozyla to Themi, by comparing with the last snapshot: a new to-do becomes a Themi task
  (assigned to the matching member, else by matching) and is nudged as usual; ticked off
  becomes done; deleted becomes cancelled; a new title or due date is copied over.
- Members are matched by first name, ignoring case.
- Themi wins while its change is pending. Reopening in Cozyla and reassigning there are
  only logged in this trial.
- First sync: open to-dos with the same title as an open Themi task are linked; other open
  to-dos come in quietly (no nudge burst for a list the family already keeps); ticked-off
  ones are left alone; Themi's open one-off tasks go onto the list.
- Like the OurGroceries mirror, configuring the list is the go-ahead for keeping it in step;
  no per-item approval.
- A failed read backs off (1 minute doubling to an hour); per-task failures retry the same way.

Tests: with the fake: first sync, each direction, conflicts, outage, and a scenario (a to-do
ticked off on the wall stops Themi's nudges).

Notes (2026-10-25):
- `themi.core.cozyla_todos.CozylaTodos`, installed only when `COZYLA_TODO_LIST` is set.
  Migration 0034: `cozyla_links` (task to to-do, pending or done, with a `version` so a change
  made mid-send isn't lost), `cozyla_seen` and `cozyla_sync`, per list.
- Due dates: Themi's date goes to the wall as the start of that day, family time; the wall's
  moment comes back as its local date. Not checked against the real wall yet: if
  `themi cozyla check` shows the wall uses another time of day (noon, say), change `_due_at`.
- To-dos from the wall come in as a light errand (kind "errand", effort 2), since the wall
  doesn't say what kind of job it is. `created_by` is cleared, so the nudge doesn't name
  someone as having added it.
- Changes made from the wall run with the listener muted, so they aren't sent straight back.
- A task that becomes a repeating chore after being sent is taken off the wall.
- Reopening or reassigning on the wall is only logged in this trial. Ticking off a to-do
  whose task is Themi's to nudge marks it done with the assignee as the doer.
- Follow-ups if the trial works: follow reopen and reassign; map repeating chores to Cozyla's
  chore chart; let the model guess the kind of a wall to-do.
- Setup: as in the README's "Cozyla to-do list" section. Nothing syncs until
  `COZYLA_TODO_LIST` is set; restart `themi run` after setting it.


### C1c · Cozyla: every list, reassigning, the family member, named lists
Status: [x] 2026-10-26
Depends on: C1b
Asked for on 2026-10-26, after the first test to-do worked on the real wall. "Erin's list" and
"Michael's list" on the wall are one Cozyla list ("To-do List") split by assignee. The account
has three lists (To-do List, Shopping List, Things to Cook) and three members: Erin, Michael and
"Madicen Family".

Done:
- Every list is read. Anything on the configured list, and anything assigned to someone on
  the others, is a Themi task; unassigned items on other lists (Things to Cook) stay lists.
  "Nudge me about any item assigned to me, regardless of the list."
- Reassigning on the wall moves the task (`TaskBoard.reassign`, which nudges the new person);
  ticking a to-do back reopens the task (`TaskBoard.reopen`); a to-do moved to another list
  stays there, and Themi's later edits go to it there.
- The member whose name says "family" stands for both of you: a to-do assigned to it is a
  shared task, on both lists and nudged to both, and a shared task goes to the wall assigned
  to it.
- Naming a list: `put_task_on_wall_list` puts a task on another list (its to-do is deleted
  and made again there), and `add_to_wall_list` adds items that aren't anyone's job, staged
  under a new `wall_list_add` category (family, can be made automatic). Asked for in their own
  words, it just happens, as with groceries. Both tools exist only when a list is configured.
- A list's first sync nudges its assigned items at low priority, so a long list trickles out
  within daily limits; unassigned ones come in quietly. `TaskBoard.prompt` takes a priority.
- Migration 0035: `cozyla_links.list_id`, `cozyla_sync.title` (list names for the tools), the
  category. The snapshot is now compared by to-do across all lists, so a move isn't a delete.

Notes (2026-10-26):
- Dry run against the real wall, on a copy of the database with every Cozyla write
  recorded instead of sent: 9 open to-dos on To-do List would become tasks (Erin 3, Michael
  6), each with a low-priority nudge; nothing from the other lists (no open assigned items);
  Themi's 5 open one-off tasks would go onto the wall with their people and due dates.
  "Madicen Family" was recognised.
- Titles link only when they match exactly: "Cat box divider" on the wall and Themi's "Split
  Merlin's cat box into two halves" would both stay. Delete one before turning it on.
- Unassigning on the wall is logged; the task keeps its person.
- Setup: `COZYLA_TODO_LIST=To-do List` in `.env`, then restart `themi run`.

### C2 · Cozyla: chores and routines (split into C2a, C2b, C2c and C3)
Read first: `cozyla-sdk`'s docs/cozyla-cloud-api.md, "Chores" and "Routines" (paths under
`/cal-server/rewards/`).

What's on the wall (read-only look, 2026-10-26): 16 chores, about half of them current.
Cleaning (bathrooms every other Friday, kitchen Wednesdays, upstairs Thursdays, bird cage
Tue and Sat), bins, feeders, and medication courses for the cats with start and end dates
("Mimi pill - 1 tab", every 2 days until 30 Oct). Most are `Everyone` with one person;
shared ones are `AnyOne` with both. Stars are 0 or 1. Reminders are off.

How they map:

| Cozyla chore | Themi chore (F6, F7) |
| --- | --- |
| `repeatsEvery` Daily/Weekly/Monthly, `repeatsEveryCounts`, `repeatsIn` | an anchored `Repeat`: "every 2 days", "every other Friday", "every Tue and Sat", "the 19th of every month" |
| `dueTime` (23:59 = no time) | `Repeat.at` |
| `startDay`; `endDay` with `repeatsUntil` false | the start; a course end, which Themi lacks: add `until` to `Repeat` |
| `AnyOne` with both | a chore for either of you (shared; whoever ticks it closes the round) |
| `Everyone` with one person | that person's chore |
| `Everyone` with both, `Rotate` | not used by the family yet: one task per person / Themi's matching |
| an occurrence `pending` / `completed` / `expired` | the round open / done (`task_runs`) / missed |
| `choreCheck` by a member on a day | `complete` by that person; Themi's completion checks the doer's occurrence |
| `coins` | kept as it is on the wall |
| steps, energy levels, minimum, escalation, step-up | Themi only (steps can go in `description`) |
| Themi's "twice a week" (floating) | no wall equivalent: stays off the chart, or pick days |

What's on the wall: 4 routines, each one person's: Walk dog (Erin, mornings), Cycle Dishwasher
(Michael, evenings), Take out bins (Michael, Tuesday evenings), Take Meds (Michael, evenings).

How they map: a routine is one person's repeating "did you...?", in a part of the day, which
is what Themi's check-in tasks (F8) and habits are. `routineType` Morning/Afternoon/Evening
maps to Themi's times of day (9 am, 2 pm, 6 pm); the schedule fields are the chores' ones.
Themi's check-ins (Erin's run: Tue, Thu, Sat at 2 pm) would show as her Afternoon routine,
and the water habit as a daily one. A routine ticked on the wall closes Themi's round; a
"Done" in Telegram ticks the routine.

The family's decisions (2026-10-26):
1. Themi wins. Its calendar is the more flexible one, and it's in charge of the wall's chore
   chart: it writes chores to match its own, and changes made on the wall to a chore Themi
   keeps are put back. Chores only on the wall come into Themi first, then Themi owns them.
2. If something is still open at the end of the day, a nudge goes out. And a check after the
   morning if the whole morning routine isn't done, and in the evening for the evening one.
3. Reminders follow how important the chore is, and get more specific as it becomes more
   overdue.

### C2a · Cozyla: chore and routine client, schedules both ways
Status: [x] 2026-10-26
Depends on: C1c
Build:
- `CozylaClient`: `chores()`, `create_chore`, `update_chore` (every field re-sent, as the API
  needs), `delete_chore`, `chore_records(day)`, `check_chore(uid, member, day, done)`;
  `routines()`, `routine_records(day)`, `check_routine(id, day, done)`. The fake serves them.
- Schedules both ways (`themi.connectors.cozyla.schedule`): a Themi `Repeat` to the wall's
  fields and back, where both can say it (every N days; every N weeks on given days; given
  days of the month; a time of day). Everything else ("twice a week, counted from the last
  time", "the first Monday", deadline chores) is put on the wall one round at a time.
- `Repeat.until`: a last day ("Mimi pill until 30 Oct"), parsed ("... until 30 Oct"), read
  back, and honoured when working out rounds; after the last one, the chore is done.

Notes (2026-10-26):
- `themi.connectors.cozyla.chores` holds the wall's shapes (`Chore`, `ChoreRecord`,
  `Routine`, `RoutineRecord`, `WallSchedule`) and the request bodies; `schedule` converts.
  Chores are created with reminders off (-1): Themi does the reminding.
- A wall chore that "repeats forever" (`repeatsUntil`) ignores its `endDay`; the family's
  chores have stale end dates from when they were made, so `Chore.active_on` follows that.
- Themi keeps one day of the month; a wall chore on "1,15" would come in as the 1st (none of
  the family's do).
- Read-only run of the new readers against the live wall: all 16 chores and 4 routines read,
  9 active chores (the cleaning, bins, feeders, flea meds, a money transfer and two Mimi pill
  courses), 7 ended ones (old courses, Tube Time, and the wall's bird cage chore, which
  ended in July). Routine records come back per day, as expected.

### C2b · Cozyla: Themi's chores on the chore chart, Themi in charge
Status: [x] 2026-10-26
Depends on: C2a
Build:
- A `cozyla.chores` job (every few minutes). Each Themi chore has one wall chore: repeating
  with the same schedule when the wall can say it, otherwise a one-off for the current round
  on its due day, moved when the round moves. Its name, people, time and schedule are made to
  match Themi's every sync; edits on the wall are put back, and a deleted one is made again
  (stop a chore in Themi).
- People: a chore's person ("Everyone" with them); a chore for either of you ("AnyOne" with
  both): a new `tasks.either`, kept every round, so either can tick it and both see it.
- Chores only on the wall: active ones (forever, or ending today or later) come into Themi
  with their schedule, people and end date, linked by title with small words ignored
  ("Clean bird cage" and "Clean the bird cage"); ended ones are left alone. Where both have a
  chore, Themi's schedule is written to the wall.
- Ticks: a tick on the wall for the current round (or an earlier one still owed) closes it in
  Themi as that person; a round done in Themi ticks the doer's occurrence. Processed ticks are
  remembered, so none counts twice.
- Wall reminders stay off; Themi does the reminding.

Notes (2026-10-26):
- Opt-in: `COZYLA_CHORES=yes`, separate from the to-do list, since Themi then rewrites the
  family's chart. The job runs every 5 minutes. Nothing is queued: each sync compares what
  the chart should hold with what it holds and writes the difference.
- Migration 0036: `tasks.either` (kept every round, so `shared` comes back each round),
  `cozyla_chores` (task to wall chore, and the last run ticked on the wall),
  `cozyla_chore_ticks` (wall ticks already acted on), `cozyla_chore_sync`.
- A chore that's due whenever ("twice a week" before its first round is done) shows on the
  wall as today, and moves day by day until it's done.
- A finished course is left on the wall (its own end stops it); a cancelled chore, or one
  that no longer repeats, is deleted there.
- A one-off round moved on the wall loses that day's tick history there; Themi keeps its own.
- Dry run against the real wall (a copy of the database, writes recorded): the 9 active wall
  chores came in with their schedules (bins, kitchen, upstairs, both bathrooms, feeders, flea
  meds, the transfer, and the two Mimi pill courses, as "either of you" with their end
  dates), and matched the wall exactly, so no writes for them. Themi's own three chores
  (upstairs bathroom, bird cage, running) would be created. 11 nudges would be queued, each
  for its chore's day. Near-duplicates to settle first: Themi's one-off "Clean the kitchen"
  and the wall's weekly "Clean kitchen"; Themi's "Clean upstairs bathroom" and the wall's
  "Clean upstairs".
- Running is a check-in: C3 moves check-ins to routines instead of chores.

### C2c · Reminders by importance: end of day, more specific when overdue
Status: [x] 2026-10-26
Depends on: C2b
Build:
- `tasks.importance`: low, normal or high. A tool sets it ("the meds really matter"); chores
  that come from the wall default to normal, and medication-like ones (pill, meds, drops,
  cream) to high.
- End of day: in the early evening (two hours before quiet hours start), one message per
  person listing what's due today and still open, low importance left out. Nothing open,
  nothing sent.
- Overdue reminders repeat by importance (high every day, normal every two days, low every
  week) and grow more specific each time: first "Overdue: X (due Tuesday)"; then the
  smallest version (the lightest steps); then a concrete suggestion, such as when today
  looks lighter, and an offer to move it or hand it to the other person. Gentle wording
  throughout (the PDA rules); never more demanding, only more concrete.
- Tests with a frozen clock across several days, for each importance.

Notes (2026-10-26):
- `themi.core.reminders`: jobs `tasks.day_end` (every 15 minutes) and `tasks.overdue`
  (hourly), and the `set_task_importance` tool. Migration 0037: `tasks.importance`,
  `overdue_reminders` and `overdue_reminded_on` (reset whenever the round or due date moves),
  and `day_end_sent`.
- "Overdue" here means past its due date: one-off tasks with a date, floating chores, and
  catch-up chores. Chores whose missed rounds roll on, and deadline chores, move by
  themselves, so they're never raised as overdue. A chore's own "overdue after N days"
  nudge (F6b) still comes; the two never land on the same day.
- Stage three's moment comes from the outbox's receptivity (the energy engine's good
  windows): "This evening looks lighter, if that helps", or "Now looks like a good moment".
  The offer names the other person ("I can move it, or ask Michael to take it").
- The end-of-day list has a deadline 15 minutes before quiet hours, so daily limits and good
  windows can't push it to the next morning.
- Medicine-like names from the wall (pill, meds, drops, cream, tabs, dose) start as high.

### C3 · Cozyla: routines, and morning and evening routine checks
Status: [x] 2026-10-26
Depends on: C2a, C2c
Build:
- Wall routines stay the wall's: Themi reads each day's routine records. After the morning
  (noon) and in the evening (two hours before quiet hours), if any of a person's routines for
  that part of the day are still open, one message lists them, with a button per routine
  that ticks it on the wall. All done: nothing sent.
- Themi's check-ins (F8) appear on the wall as that person's routine for their part of the
  day, kept by Themi as chores are; a tick on the wall closes Themi's round.
- Routine ticks become energy signals for the Shadow Calendar ("Cycle Dishwasher" is Erin's
  idea #4 signal, without hardware); people see words, never scores. Revisit H1 after this.

Notes (2026-10-26):
- `themi.core.cozyla_routines`, job `cozyla.routines` every 15 minutes, under the same
  `COZYLA_CHORES=yes`. Migration 0038: `cozyla_routines`, `cozyla_routine_ticks`,
  `routine_checks_sent`.
- The morning check runs from noon and the evening one from an hour before quiet hours,
  once each per person per day, with a deadline 15 minutes before quiet hours. Afternoon
  routines aren't checked (not asked for).
- Energy: one signal per check, as `device_activity` (so the person's "activity from household
  devices" switch covers it; its description now mentions the wall's routines): +0.5 when
  that part of the day is done, -0.5 when it isn't.
- A check-in becomes a routine only on fixed days (the wall's routines always repeat); a
  "3 times a week" check-in stays a chore. A routine can't change hands on the wall, so a
  check-in given to someone else is deleted there and made again for them.
- The scenario harness's `tap` sees buttons on sent messages only; the test taps the edited
  message's keyboard directly.
- Dry run against the real wall (a copy, writes recorded): Erin's run would become her
  Afternoon routine (Tue, Thu, Sat); her walk, Michael's dishwasher, meds and bins routines
  stay the wall's and are only read. At 10:58 nothing was due to be checked.
- H1 (dishwasher): "Cycle Dishwasher" now feeds the energy model each evening; try that
  before any hardware.

### F10 · Feedback: due times, one nudge at a time, plain phrasing, check-in reviews
Status: [x] 2026-10-26
Depends on: F8, C2b, C3
From the family's reports of 2026-10-26 (bugs #14 and #15, ideas #11, #12 and #13), the
first with the Cozyla sync on (`themi run` restarted at 11:10 with the to-do list and the
chore chart).

Done (failing tests first for the bugs):
- Bug #14 ("do not prompt tasks until they're due"): "Today around 2, remind me to answer the
  tutoring email" was asked about at 11:17. Tasks gain a due time (`tasks.due_time`, migration
  0039; `create_task`'s `due_time`, and a time with no date means today), and no nudge goes
  out before a task's day or time, whatever path sends it (the rule is in `TaskBoard.prompt`).
  Labels for later days ("Due Sunday:") stay, for anything sent early another way.
- Bug #15: "Move vacuum upstairs bedroom to chores in Cozyla" had Themi looking for a list
  called Chores. `put_task_on_chore_chart` (`tasks.on_chart`, migration 0040) moves a one-off
  task to the chart: the to-do sync takes it off the lists, the chore sync puts it on the
  chart for its day, and a tick on either side closes it. The list tool's refusal points
  there; `put_task_on_wall_list` brings it back.
- A chore for either of you was listed to the model as "shared, overdue" (in the reports'
  open items, "Bring bins in" due Wednesday on Monday); now "either of you".
- Idea #11 ("only prompt one task at a time"): while a task nudge is unanswered (open, not put
  off), the next waits, for up to two hours. The outbox gains per-kind gates, checked at each
  flush rather than stored, so answering lets the next go at once. The end-of-day list is its
  own kind (`task_summary`) and doesn't wait.
- Idea #12 ("default to plain language; let each person customise phrasing for PDA"): a
  per-person phrasing style, plain (default) or gentle, and notes in their own words
  (migration 0041). It shapes the conversation prompt, task nudges ("whenever it suits" is
  gentle only), habit check-ins, the softener ("Up next: ..." when plain) and the rewriter.
  Set on the settings page or in chat (`set_phrasing`). Shielding's strictness stays.
- Idea #13 (check-in reviews): after 4 check-ins, Themi asks whether one is helping (Helpful,
  Not really, Let's talk later, Stop asking). Helpful doubles the wait; three of those end it;
  Not really offers to stop it; Later keeps the wait. `set_check_in_reviews` changes it for one
  check-in or all; a settings checkbox too (migration 0042, `themi.core.checkin_reviews`).

Notes (2026-10-26):
- Plain is the default for everyone, existing members included, as asked. Erin's gentle
  phrasing strength (1) and shielding are unchanged: plain isn't demanding, and the checker
  still runs.
- Data left for after the restart: putting Erin's "Vacuum upstairs bedroom" on the chart
  (ask Themi again, or `put_task_on_chore_chart` for task 1).
- Still open from the reports: the near-duplicate chores ("Clean the kitchen" and the wall's
  "Clean kitchen"; "Clean upstairs bathroom" and "Clean upstairs") now both exist in Themi.

### C2d · Cozyla: one chore on the chart at a time
Status: [x] 2026-10-26
Depends on: C2b, C2c, F10
From Erin's ideas #16 and #17 (2026-10-26): a long chore chart is overwhelming, so by default
she sees one chore at a time. Her rule 13 ("one flexible task per day plus strict deadlines")
asked for this, but a rule can't change what the sync writes; this is the feature. The
family's decisions (2026-10-26): one at a time (tick it and the next appears), chores for
either of you count, a single limit for now, and deleting it on the wall means it's done.
Build:
- A per-person `chart_limit` (0 = no limit): the settings page and `set_chore_chart_limit`.
- For someone with a limit, only that many of their chores are on the chart; the rest wait in
  Themi, off the wall. High-importance chores (medicines, or anything set high) always show and
  don't count. A chore for either of you counts for the person with the limit; it stays on the
  wall for the other person.
- Which one: chores due today or earlier (or due whenever), the most overdue first, then by
  importance, then the oldest. Nothing is pulled forward by itself (#14: nothing before it's
  due). A chore that's up stays up until its round is done or moves, even across days, and
  shows on the wall as a one-off for today.
- Ticking it (on the wall or in Themi), or deleting it on the wall, completes it; the next sync
  brings up the next.
- In chat, `change_chore_chart`: "a different one" puts the current chore back for today and
  brings up another (a named one, or Themi's next pick, or the next coming up if nothing else is
  due); "another one" adds one more on top of the limit.
- Waiting chores send no nudges, aren't on the end-of-day list and aren't raised as overdue;
  a chore that comes up gets its nudge then.
- The model is told whether a chore is up or waiting its turn, and that the limit is a setting,
  not a rule.

Notes (2026-10-26):
- `themi.core.chore_chart` (`ChartQueue`), run by the `cozyla.chores` sync, so it's on only
  with `COZYLA_CHORES=yes`. Migration 0045: `members.chart_limit`, `cozyla_chart_picks` (what's
  up, for which round, whether it's an extra and whether it's had its nudge) and
  `cozyla_chart_skips` ("a different one" passes a chore over for that day). The limit is on
  the settings page and in chat (`set_chore_chart_limit`); the feedback report shows it.
- `on_chart` and `is_routine` moved to `chore_chart` (the sync imports them from there).
- Waiting chores are held back through `TaskBoard.holds`: `prompt` skips them, the end-of-day
  list and the overdue job leave them out, and the sync withdraws their queued nudges. A chore
  that comes up gets its nudge then, unless it was asked for in chat (the reply says so).
- Fixed on the way: a repeating chore's round done in Themi kept pointing at its answered
  nudge, so the one-nudge-at-a-time gate held the next nudge for two hours. A done round now
  clears it.
- On the wall: when the limit goes on, the person's waiting chores are deleted from the chart
  (their wall history goes; Themi keeps its own) and come back as one-offs for the day they're
  up. A chore for either of you waiting for Erin stays on the wall as Michael's alone. Deleting
  a chore for either of you that's up for Erin counts as hers, since the wall doesn't say who
  deleted it.
- Dry run against the real wall (a copy, writes recorded), Erin at 1: nine of her chores would
  leave the chart and "Bring bins in" would become Michael's there; the Mimi pills, the flea
  meds and the feeders stay. Six queued nudges for waiting chores (kitchen, upstairs, both
  bathrooms, bins, the transfer) would be withdrawn. Nothing would be up on Monday, since none
  of her chores is due until Tuesday, when the bird cage comes up.
- Setup: `themi run` restarted (migration 0045), then Erin's limit set to 1 (on the settings
  page, by asking Themi, or for her).
- Live (2026-10-26, 15:50): restarted, Erin's limit set to 1 and rule 13 deleted, as asked.
  The real chart then held the pills, flea meds, feeders and Michael's bins; her first chore
  comes up Tuesday.
- Added after: each person chooses whether chores for either of you count toward their limit
  (`members.chart_counts_shared`, migration 0046, on by default as the family decided): the
  settings page, or `set_chore_chart_limit`'s `shared_count` (its `limit` of -1 keeps the
  number). Off, those chores always show for them.
- A possible next step: picking a lighter chore on a low-energy day.

### F11 · Feedback (2026-10-27): put off until a time, summaries, finding events, routine items
Status: [x] 2026-10-27
Depends on: K2, K4b, C3
From the family's reports of 2026-10-26/27 (`themi feedback`): ideas #18, #19 and #23, bugs #20
and #22.

Notes (2026-10-27):
- #18 ("If I give a specific time that I will do a task, I shouldn't get a nudge before that
  time"): "I'll do it tonight around 9" could only snooze for four hours, so the nudge came
  at 7:32 and Themi had said "set for tonight at 9". `snooze_task` takes `until` (HH:MM,
  today, or tomorrow if passed; empty: four hours, as "Later" still is), and the end-of-day
  list leaves out a task put off past now. The draft personal rule Themi proposed for it
  (13) was discarded.
- #19: summaries are "Tue 27 Oct:" and one bulleted list in the order of the day (all-day
  events, then anything with a time, then the rest; the partner's events marked with their
  name). `day_summary` sends it itself, word for word (the model had reworded it). The PDA
  shield now reads a bullet line as a list item, not an order ("- Call the vet"). Erin's
  bird cage was missing from tomorrow's list: a chart chore waiting its turn is only left out
  for today.
- #20: "her tutoring appointment" didn't find "Tutor Gabriel (Illems)" on the Madicen Family
  calendar. `events.title_matches`: every word they used, bar fillers ("the",
  "appointment"), matches a title word, the same or a form of it (a shared start of five
  letters or more, most of the shorter word). Used by `drive_time` and by moving and deleting
  events.
- #22: an item for a routine on the wall went to the calendar, then the chore chart, then a
  new list. `add_to_wall_routine` (title, Morning/Afternoon/Evening, repeat: '' for just
  today or a schedule phrase), category `wall_routine_add` (member, may become automatic),
  at once when they said "routine" and the item. It's the wall's own routine, so the morning
  and evening checks include it. The wall's routines have no end date, so a just-for-today
  item is deleted the next day (`wall_routine_once`, migration 0057). A prompt line keeps
  routine items off calendars, chores and lists.
- #21 (Google Home) is research: prompt R2.
- #23 (Erin: "this rule should probably be the default for everyone"): "drink black tea
  tomorrow at 7" was offered for the family calendar, and she locked a personal rule (14)
  against it. Now a task someone makes for themselves (or that came from the wall with
  nobody named), not shared or for either of them, is never offered for the family
  calendar; ones for the other person, or shared, still are. Rule 14 was retired (unlocked).
- Setup: restart (applies 0057). The mistaken personal "Evening Routine" list from #22 (on
  the wall, with "Replace vacuum water") is still there, waiting for the family's OK to
  delete it.

### F12 · Feedback (2026-10-27): heads-ups explained, "one of us", emoji on the wall
Status: [x] 2026-10-27
Depends on: K4b, C2b, C3
From the family's reports of 2026-10-27: bugs #24 and #26, idea #25.

Notes (2026-10-27):
- #24 ("the time to get ready should be factored into nudges for when to leave"): it already
  was (the heads-up comes at the leave time minus getting ready), but Themi didn't know and
  said there were no advance reminders, then drafted a rule (set aside). A prompt line now
  says how heads-ups work, and `drive_time` says when the heads-up comes and to whom ("goes to
  Husband, whose calendar it's on"), or that it's switched off. Known gap: a heads-up goes to
  whoever's calendar the event was read from, so an event for Erin on the Madicen Family
  calendar (read through Michael's account) reaches Michael; Erin hasn't linked Google yet.
- #26 (Erin: "make one of us assemble a grocery order", urgent): it became her task alone, at
  normal importance. `create_task` takes `assign_to` "both" ("one of us", "either of us": on
  both lists, asked of both, whoever does it closes it; `TaskBoard.make_either`) and an
  `importance` ("urgent" is high). `IMPORTANCE` moved to `themi.core.tasks`.
- #25 (Michael: "pick appropriate emoji based on the task description"):
  `themi.connectors.cozyla.emoji`, a household keyword list (bird 🦜, cat 🐈, pill 💊, bins 🗑️,
  run 🏃...) in the wall's own format (`czl_chores_emoji#_#<name>#_#<emoji>`,
  `czl_routine_emoji#_#...`). New chores and routines get one; Themi's own plain default (the
  broom, the bed) or no icon is replaced once when there's a real fit; an icon the family
  chose is never touched. Dry run on the real wall: Clean the bird cage 🧹 to 🦜, both Mimi
  pills to 💊, Go for a run (routine) to 🏃; nothing else.
- Setup: a restart.

### F13 · Feedback (2026-10-27): problems talked through, mentions, nicknames, slow replies
Status: [x] 2026-10-27
Depends on: F5, 11
From the family's reports of 2026-10-27: bugs #29 and #30, ideas #28 and #32 (#27, #31 and
the fuller #28 are prompts E1, S5 and M1).

Notes (2026-10-27):
- #30 ("an idea for us to implement, not a rule for Themi"): a prompt line for problems ("how
  can we stop losing the pacifiers?"): two to four ideas, they pick, then ask about actions
  (buy something, a task or routine, raise it with their partner), only what they agree to,
  and a summary kept with `remember_fact`. `propose_rule` says ideas for the family are a
  conversation, never rules. Also a bug: "I swear all our pacifiers keep disappearing??"
  put pacifiers straight on Things to Buy, because the "asked for" check only looked for the
  item's name. `groceries.asks_to_add`: the message also has to ask (add, put, need, buy,
  get, out of, running low...), or carry on one that did ("and limes", "batteries too";
  `ToolContext.previous_text`). Groceries, Things to Buy and named lists all use it.
- #28 (records of general questions): a prompt line keeps a one-line note of an answer worth
  keeping. A fuller record of conversations is prompt M1.
- #32 (nicknames): "Michael calls Erin Hundo" was saved as Erin's personal note, so Michael's
  conversations wouldn't know it; moved to a household note. A prompt line: nicknames are
  household notes that say who calls whom, read from the speaker's side.
- #29 ("why that exchange took so long"): two model calls of about 29 seconds each, on the
  free Gemini key. Interactive calls never wait more than 20 seconds for a retry, so it was
  slow answers, retries, or both; probably the free tier's limits while Erin's newly linked
  inbox was triaged on the same key. Nothing recorded it, so now `ai_calls` (migration 0058)
  keeps a week of every call: task, backend, seconds, time waited, retries, last status, ok.
  Each call sends about 10,000 tokens (55 tools' schemas are most of it); trimming them is a
  possible follow-up.
- Setup: restart (applies 0058).

### F14a · Feedback (2026-10-27): one card per event, nudges at a time, check-ins kept in Themi, whose day
Status: [x] 2026-10-28
Depends on: K3, K5, C1b, K2
From the family's reports of 2026-10-27: bugs #35, #39, #40, #41 and #43. F14b takes the
rest of that day's bugs; ideas #37, #42 and #44 are prompts X1, B1 and T1; #33 (burnout
recovery mode) and #34 (body double mode) wait for Erin's spec.

What happened, from the database and logs:
- #35 (Michael: "review this exchange"): "add a lunch at Merit this Sunday" became an
  all-day card. "It should be at lunch" staged a second card (12-1) and left the all-day one
  waiting. "Go ahead and add to calendar" then answered the old all-day card with
  `answer_waiting_item` and staged a third. Now three events: all day, 12-1 and 12-1.
  Separately, the first write to the family calendar made a new "Themi" calendar on Erin's
  account (the first admin's), which neither the wall nor Michael sees.
- #39 (Erin: "prompt me to run at 2pm" staged a calendar block, not a nudge):
  `block_time_for_task` has nothing telling a nudge at a time from time on the calendar.
- #40 ("I checked off the run on the wall... it's still asking"): the tick did sync (14:53),
  but the 14:00 check-in kept its Done/Later buttons. `_complete_round` clears
  `prompt_outbox_id` before `withdraw_prompt` reads it, and `withdraw_prompt` only cancels
  unsent nudges.
- #41 (an extra "drink some water" check-in, just for today, went onto the wall's to-do
  list): one-off check-ins sync to the wall like any task.
- #43 ("waste bins and tea time are not mine"): "what else do I have today?" was answered with
  `partner: true`. Erin now reads the Madicen Family calendar too, so its events came twice,
  once marked "(Michael)", and Michael's own Tea Time was there.

Build:
- A newer card for the same event (same title, same day, same calendar, still waiting) takes
  the older card's place. The older one is withdrawn and its message says it was replaced
  (`Autonomy.withdraw`, a listener the approvals UI uses to edit the card). An event already
  on that calendar with the same title and times isn't added again ("already on the family
  calendar"). One that Themi made, with the same title on the same day but other times, points
  to `move_calendar_event`.
- A meal with no time (breakfast, brunch, lunch, dinner) isn't all day: the usual time
  (8, 10:30, 12, 18), read back on the card so it can be changed.
- "Prompt me / remind me / nudge me at 2" about an existing task is `snooze_task` until then.
  `block_time_for_task` refuses a request that asks for a nudge and doesn't mention the
  calendar or blocking time.
- A task done anywhere other than its own buttons (the wall, chat, the other person): its
  check-ins sent in the last day lose their buttons and say it's done. The bug in
  `_complete_round`'s order is fixed too.
- A one-off check-in task stays in Themi: never on the wall's to-do list.
- Day summaries: an event read through two people's accounts shows once. An event on a
  calendar more than one person reads is marked with that calendar's name ("Madicen Family")
  instead of a person. Partner events only when the message asks about both of them or the
  partner (we, us, our, both, the partner's name), whatever the model sent.
- Tests for each, failing first; a scenario for the replaced card and the summary.

Notes (2026-10-28):
- #35: `Autonomy.withdraw(action, reason)` declines a waiting action as the system (audit
  "withdrawn") and tells `withdrawn_listeners`; the approvals UI edits the card to "Replaced
  by the newer card." with no buttons. `Events.replace_waiting` does this for an
  `add_calendar_event` card with the same title (`name_key`), local day and calendar; the
  very same event already waiting is a `ToolDeclined`. `Events.made_that_day` looks only at
  events Themi made (`themi_events`): same times is "Already on ...", other times points to
  `move_calendar_event`. Meals are 08:00, 10:30, 12:00, 18:00, an hour long.
- #39: `block_time_for_task` fails when the message has prompt, remind, nudge, ping or "check
  in with" and none of block, calendar, schedule or "time for". `snooze_task`'s description
  covers "prompt me to run at 2pm".
- #40: `TaskBoard.complete(..., tapped=)`: sent nudges of that task from the last 36 hours
  are edited to "Marked done: X. Thank you." with no buttons, except the one whose button
  was tapped (the button handler edits that one itself, as before).
- #41: `cozyla_todos._not_a_todo`: repeating, on the chart, or a check-in. A check-in
  already on the wall stays linked until it's done.
- #43: `Entry` now carries `calendar_id` and `event_id`. Day summaries list an event read
  through two accounts once; one on a calendar more than one person reads
  (`member_calendars`) is marked with its name, e.g. "(Madicen Family)", and shows without
  `partner`. `day_summary`'s `partner` only counts when the message has we, us, our, both,
  together, everyone, family, husband, wife, partner or the other person's name. The model's
  calendar context drops the duplicates too.
- Setup, the family calendar: Themi's first family-calendar write (2026-10-27 11:53) made a
  new "Themi" calendar on Erin's account, the first admin's, because none had been chosen.
  The wall and Michael don't see it. On it now: three "Lunch at Merit" events (all day,
  12-1, 12-1) and "Contact Erin's parents about babysitting". Choose the family calendar on
  the admin page (Michael's account and "Madicen Family", say, if the wall shows that
  one), then delete the leftovers. Also waiting: card 78, Erin's 2-3 pm run block (#39),
  which can be declined. Done 2026-10-28: the family chose "Madicen Family" (no account
  chosen, so it's Erin's, which owns it too). The 12-1 lunch and the babysitting reminder
  were copied there with their ids, the other two lunches marked deleted, and the stray
  "Themi" calendar deleted.
- No migration; a restart.

### F14b · Feedback (2026-10-27): routine order, email setup, spending isn't shopping, passing messages on
Status: [x] 2026-10-28
Depends on: F14a, C3, E1
From the family's reports of 2026-10-27: bugs #36, #38, #45 and idea #46, plus one found
while reading them.
- #38 ("add take wegovy and drug a bean as the first two tasks of my morning routine" went at
  the end, and only for today): `add_to_wall_routine` gets a position (start, end, or after an
  item), if the wall's routines keep an order (find out from the client first). "Add to my
  morning routine" with no "just today" repeats every day.
- #45 ("remind me which [senders] I needed to evaluate?" got "you haven't set up any watched
  inboxes"): the model called `list_expected_emails`. A tool that says, per linked inbox,
  what's set: watched labels, urgent senders, and the sender suggestions still waiting.
  Michael's "Change them" button answered "None." (10:57) as well.
- #36 ("just spent $51.97 on door dash" was staged for Things to Buy): a spend isn't
  something to buy. The list tools refuse an item that's a price or a past purchase. What a
  spend becomes is prompt X1.
- #46 (Michael: "show routines as a bulleted list"): the morning and evening routine checks
  list what's open as bullets, as day summaries do.
- Found while reading: "can you tell Hundo 'I Wuv U ❤️'?" was saved as a note (`remember_fact`)
  and answered "I've saved that for her". Until Liaison (prompt 34), Themi says plainly that
  it can't pass messages on yet, and nothing is saved as a note.

Notes (2026-10-28):
- #38: the wall keeps each routine's place as `displayOrder` (Morning 1000s, Afternoon
  2000s, Evening 3000s, new ones last), read from the real wall. `add_to_wall_routine` takes
  `position` ('end', 'start', 'after: <item>', matched with `events.title_matches`). The
  executor sends the order on create, reads the routine back, tries once more with an
  update, and if the wall still keeps its own order says "it went at the end... needs
  moving there". Not tried against the real wall yet: whether it takes `displayOrder` shows
  the first time someone asks. `repeat` '' is now every day; 'today' (or '' in a message
  that says today, tonight, "just for" or "this morning/afternoon/evening") is once. Cards
  from before keep their old meaning ('' with no `once` field: once). Erin's two items from
  #38 were deleted the next day as one-offs; they can be added again.
- #46: routine checks are "Morning routine, still open:" and a bullet per item.
- #45: `inbox_setup` (email group), from `SenderSuggestions.setup`. Michael's "Change them"
  tap (10:57) was a quick reply the model made; its "None." was the model's, with nothing
  to look at. Now there is.
- #36: `groceries.refuse_spending`: "spent", "paid", "cost me" or "was/got charged" in the
  message, or a price in an item (grocery and Things to Buy only; not other named lists),
  fails the add and asks the model to say Themi doesn't track spending yet. X1 is where a
  spend goes.
- Relays: `remember_fact` fails when the message opens "tell X ...", "let X know",
  "message/text/send X ..." (not me, myself or us), and a prompt line says Themi can't pass
  messages on yet. Liaison (34) will relay them.
- No migration; a restart.

### X1 · Spending: takeout and business expenses
Status: [x] 2026-10-28
Depends on: F14b, 23
From Michael's bug #36 ("door dash and eating out messages don't work at all") and idea #37
("track business expenses"), 2026-10-27. Read first: "Module behaviour" → D (takeout budget);
prompt 35's takeout rescue needs the month's takeout total.
- "Just spent $51.97 on DoorDash", or a takeout receipt from email (triage already finds them),
  becomes a spend: amount, where, kind (takeout, eating out, business, other), who, when.
  Told back with the month's takeout so far against the family's budget, in words.
- Business expenses: marked as business when they say so ("for work", "business lunch"). A
  monthly list to export (CSV) from the website, with the receipt email linked when there is
  one.
- Asking ("how much takeout this month?", "what are my business expenses for October?").

Notes (2026-10-28):
- The plan says receipts keep the takeout budget "so nobody logs spending by hand"; the
  family asked for chat too (#36), so both feed one table. Migration 0060 `spending`:
  member, cents, place, kind (takeout, eating_out, other), business, spent_on, email_id
  (unique), source (chat, email).
- `themi.core.spending`: `log_spending` (a plain tool: Themi's own record, nothing outside
  changes), `spending_summary` (month, takeout / eating_out / business / all),
  `mark_business_expense`, `remove_spending`, in a new "spending" tool group (spent, paid,
  $, expense, budget, takeout, DoorDash...). A takeout reply carries "Takeout this month:
  $X of the $Y budget ($Z left)". Money is shown as money; that's not an energy score.
- The receipt reader asks for `total_cents` now (falls back to the line prices). A takeout
  receipt becomes a spend; the same amount said in chat within two days is the same meal
  (the receipt joins it), and a chat spend matching an emailed one is declined.
- Business expenses are each person's own: listed and exported only for them, changed
  only by them (an admin can fix another's household takeout, not their business ones).
  Website: Spending (nav), a month at a time, and `/spending/business.csv?month=YYYY-MM`
  with a Gmail link to the receipt when there is one.
- F14b's refusal on list tools now says to use `log_spending`.
- Prompt 35 can read the month's takeout from `Spending.month(kind="takeout")`.
- Setup: restart (applies 0060). Michael's $51.97 DoorDash from 2026-10-27 isn't in it;
  he can say it again.

### B1 · Breaks: a rest mode that ends with a question
Status: [x] 2026-10-28
Depends on: 17, F3
From Erin's idea #42, 2026-10-27: "put Themi into rest/break/busy mode... At the end of the
designated rest time, Themi will alert the user that time is up, giving the options 'End
break' or 'Extend break by [amount of time]'. The length of the offered extension should be
customizable."
- "I'm taking a break" / "rest for 30 minutes": no task nudges until it ends (what they asked
  for still comes, and anything set to come during breaks). /pause's machinery, with an end.
- At the end: "Break's up" with [End break] [Extend by N min]. N is a personal setting
  (default 15).
- Later: Themi suggests a break when the Shadow Calendar sees a long run of effort (asked,
  never started on its own).

Notes (2026-10-28):
- `themi.core.breaks`: `start_break(minutes)` (0: half an hour; up to 8 hours; a break
  going on gets the new end), `end_break`, and `/break 30`. A break is a pause on the new
  "break" topic (task, task_summary, habit, routine and review messages), so held nudges
  wait in the outbox; replies, approvals and urgent alerts still come.
- "Break's up. Ready to carry on, or a little longer?" goes at the end (NORMAL, with a
  deadline five minutes on, so the daily limit doesn't hold it), with [End break] and
  [Extend by N min]. Deviation: the pause runs ten minutes past the end, so nudges don't
  land in the same minute as the question; answering ends that wait at once
  (`release_held`, as /resume does).
- Migration 0061: `breaks`, and `members.break_extend_minutes` (5-120, default 15), on My
  settings.
- Follow-ups from the idea: Themi suggesting breaks itself, and breaks that bring a chosen
  set of prompts.
- Setup: restart (applies 0061).

### T1 · Tasks: urgent and important
Status: [x] 2026-10-28
Depends on: F12, C2c
From Erin's idea #44, 2026-10-27: urgent (a hard due date that's soon) and important (there
are consequences if it's ignored for good) as two separate scales, for tasks, emails and
everything else.
- Which task to offer next: urgent and important first, then urgent only, then important
  only, then neither. An important-only task left waiting too long moves ahead of urgent-only
  ones.
- Urgency comes from the due date; importance is what F12's `importance` becomes (said, or
  judged at creation and changeable). Email triage's urgent flag maps onto the same two scales.
- Never shown as numbers or scores.

Notes (2026-10-28):
- `themi.core.priority`: urgent is a due date today, tomorrow or past (sooner first);
  important is importance high (normal and low aren't, low last). The order: urgent and
  important, then an important-only task waiting a week or more since it was made or last
  done, then urgent only, important only, neither.
- Where it applies: task nudges are asked one at a time (F10), so when several are waiting,
  `Outbox.orders["task"]` puts them in that order at each flush (other messages keep their
  places). A nudge that's due on its own still goes when it's due.
- Open items (what the model sees) carry the words: "urgent and important", "urgent",
  "important". A prompt line has the model suggest in that order when asked what's next.
- F12's "urgent is high" changes: `create_task`'s importance means consequences; "urgent",
  "asap", "right away" with no date makes it due today (in code, from the message).
- Email: triage's urgent mail already alerts at once; nothing else changed there. Tasks
  made from email would carry the same two scales.
- No migration.

### F15a · Feedback (2026-10-28): changing a task's time, one task not two, reminders not events
Status: [x] 2026-10-28
Depends on: F11, F14a, T1
From the family's reports of 2026-10-28: bugs #54, #56, #52 and the rest of #47.
- #54 ("on Friday afternoon, remind me to drink green tea", then "a bit earlier... 5pm is
  too late"; "extra reminders for the tutoring at 2pm and 3pm" for tomorrow's session):
  there is no tool to change a task's time. The model used `snooze_task`, which only knows
  today or tomorrow, so all three were set to come up today. When it then moved the day,
  `reschedule_task` changed the date and left the snooze, so they would still come today.
  The fix: `reschedule_task` takes a date and/or a time (and a window's start). It clears
  any snooze, takes back the queued nudge and queues it again for the new moment, and says
  both back with the weekday ("Thu 29 Oct, 2 pm"). `snooze_task` stays for "later" and
  "tonight at 9", and its reply names the day when it isn't today. Reminders tied to an
  event ("2 and 3 before tutoring tomorrow") take the event's day, and a prompt line says
  "tomorrow" or "Friday" from earlier messages carries over.
- #56 ("Mimi pill should always check at 9pm, and never before"): Themi made a second,
  one-off "Mimi pill" task at 9 pm and said "every day". The repeating task wasn't touched,
  so it nudged at 9 am, and Michael saw the pill twice. A repeating task's time goes in its
  schedule (`set_task_schedule`, "every 2 days at 9pm until 30 Oct", keeping the course end
  and the start). `create_task` refuses a task whose title matches an open one
  (`events.title_matches`) and points to the tools that change that one.
- #52 ("Urgent important make sure Michael checks in with me before implementing idea 48"):
  the task for Michael was right; the family calendar card alongside it wasn't.
  `add_calendar_event` refuses when the message is a reminder or to-do with no event in it
  (remind, make sure, don't forget, check in with), as `task_blocks` refuses nudges (F14a).
- #47 (rest): "add them until further notice" for two routine steps got "Which steps were
  those?", then a "Take Wegovy" task marked done. The steps had been named in the earlier
  message. F14b already fixed the first half (no "just today" unless said). A scenario: the
  steps named a message earlier go back on the morning routine, every day.

Notes (2026-10-28):
- #54: `TaskBoard.reschedule` takes `due_time` and `from_time` (left as they are unless
  given). It ends any snooze, takes back the queued nudge and asks again for the new
  moment (both people for an either task), and reads back "Thu 22 Oct, 2 pm". The tool's
  `due_date` '' now keeps the date and 'none' takes it away; before, '' took it away.
  The day carrying over from earlier messages is in the tool's description, not a prompt
  line. `snooze_task` names the day when it isn't today ("waits until Thu 22 Oct, 8 am").
  Rescheduling now always asks the nudge again, the wall's date changes too: before,
  a nudge already queued kept the old moment.
- #56: a time for a repeating chore goes in its schedule (`repeat.at`), keeping its start
  and end. `create_task` refuses a title whose every word is in an open task's title
  (`events.title_matches`), for that person or anyone, and says which tools change it.
- #52: deviation from the plan. The plan offers dated tasks for the family calendar so
  they show on the wall. Now that the wall's own lists are synced (`services.wall`), the
  task is there already, so no calendar card. Without the wall, nothing changed.
- #47: `add_to_wall_routine` keeps an item when the message says "until further notice",
  "from now on", "every day/morning...", "always", "for good" or "permanently", even if
  the model sent "today". The model asking "which steps?" was the free Gemini model
  missing context; P2 is where a better model comes in.
- Data fixed by hand on 2026-10-28 (copy of the database from before, in the session
  scratchpad): green tea due Fri 30 Oct, 1 pm; the tutoring reminders on Thu 29 Oct at 2
  and 3 pm; both Mimi pill courses at 9 pm, today's round at 9 pm; the extra "Mimi pill"
  task cancelled; Michael's stale summary removed from the outbox.
- No migration; a restart.

### F15b · Feedback (2026-10-28): summaries and cards on time, one morning message
Status: [x] 2026-10-28
Depends on: F15a, F10
From the family's reports of 2026-10-28: bugs #57 and #49, and Michael's held cards (#53 is F15c).
- #57 ("my day summary didn't show up at the specified time (9:00 am)"): the summary is
  NORMAL priority. Michael had used his three messages for the day, so it was queued for
  8 am the next day, still headed "Wed 28 Oct". A summary he set a time for doesn't count
  against the daily limit (it has a deadline, as "Break's up" does). One that can't go the
  same day is dropped, never sent late.
- Approval cards held by the limit: Michael's reply draft to Juan (since 10-27), two
  "mark as read" cards, and a calendar card for that day's UPS delivery all waited for the
  next morning, so he only saw them on the website. Cards go the same day. A card about
  something that is over by the time it would go (an event that has ended) is withdrawn
  and declined as "too late", never sent.
- #49 ("it should not give more than one task prompt at a time. The morning summary should be a
  single message with a list of what's happening today"): at 8:00, when quiet hours ended,
  Erin got six messages: two nudges for one task ("Was due yesterday" and "Overdue", both
  task 37), two reply cards, and two lists of senders that might be urgent. The fixes:
  - One nudge per task: an overdue notice replaces that task's waiting nudge.
  - When several messages are waiting for the end of quiet hours, the task nudges and
    notices go as one morning list ("This morning: ..."), with a button per task. Cards
    still go one at a time after it.
  - The sender lists are E2's to replace.

Notes (2026-10-28):
- Migration 0062: `expires_at` on `outbox` and `pending_actions`. `Outbox.send(expires=)`:
  a row still waiting at that moment is deleted at the next flush and logged, never sent
  (the status column only allows queued, sent and failed, so expired rows go the way
  cancelled ones do). `Autonomy.stage(expires=)`: `expire_stale` (the hourly
  `approvals.expire`) lapses the action and edits or takes back its card.
- #57: the morning summary has its chosen time as its deadline, so the daily limit doesn't
  hold it, and it expires at local midnight. Quiet hours still hold it.
- Held cards: every card has a deadline two hours after it's asked (`CARD_WITHIN`). It
  still waits for a good moment, but the daily limit can't push it to the next day. A
  calendar card from an email expires when the event ends.
- #49: `TaskBoard.prompt` takes back any nudge for that task still waiting for that
  person. That was also why the one-at-a-time gate let the second one through: the newer
  queued nudge became the task's `prompt_outbox_id`. The morning list is a new outbox
  hook, `Outbox.bundlers`. When at least two task nudges are ready for one person within
  45 minutes of their quiet hours ending, they go as one message: "This morning:", a line
  per task with its label, and a "✓ title" button each (six at most). That message
  becomes each task's nudge, so the next one waits its turn (idea #11). A tick marks that
  one done and edits the list down to the rest, or to "This morning's list: all done."
  The tasks left aren't nudged again that morning; the end-of-day list still names them.
  Later in the day nudges still come one at a time.
- Tests: `test_reminders`' rhythm test counted two waiting nudges for one task; it now
  counts the raises. The harness's `tap` finds buttons from edits too.
- Not done here: the two sender lists at 8:00 are E2's to replace.
- Setup: restart (applies 0062). Michael's cards already queued for tomorrow 8 am were
  queued before this, without a deadline, so they still wait for tomorrow.
### F15c · Feedback (2026-10-28): the urgent email that shouldn't need a rule
Status: [x] 2026-10-28
Depends on: F15b, E1
From Michael's bug #53, 2026-10-28 (split from F15b).
- #53 ("The Charles Schwab email is urgent and shouldn't be archived" became a proposed
  rule; "probably shouldn't need a rule for this"): Themi acts on that email. It's kept, and
  taken out of the archive if it was archived. Themi offers "always urgent" for that sender
  (E1's button), and `propose_rule` refuses requests about one email or sender.
  Also: Google security alerts were called urgent "(money)"; triage's urgent reasons get an
  "account security" reason.

Notes (2026-10-28):
- `keep_email(email)` (triage, email group). It takes their newest email from the last 30
  days whose sender or subject has every word they used (`events.title_matches`), across
  their own linked inboxes. It counts the email as urgent (Themi's own record) and
  withdraws any waiting offer to archive it ("Kept: it isn't noise after all."). If
  Themi archived it, the email goes back in the inbox: a new category, `email_keep`
  (migration 0063, can be automatic), and executor `gmail.unarchive` (adds INBOX). Being
  asked counts as the yes. If the sender isn't urgent already, Themi asks with E1's
  button ("Always urgent: ...", recorded in `sender_suggestions`).
- `propose_rule` fails on "this/that/the ... email" with no always, every, all, any or
  "from now on", pointing to `keep_email`. It also fails on "X emails are urgent" or "mail
  from X is ... urgent", pointing to `set_urgent_senders`. Rules about urgent mail in
  general ("never archive urgent emails") still go through.
- Triage's urgent kinds gain `security` ("account security"): sign-in alerts, new access
  to an account, unrequested password resets; not money unless money moved.
- Michael's draft rule from #53 is still a draft; he can set it aside. The Schwab email
  was never archived (it's still in his inbox).
- Setup: restart (applies 0062 and 0063).

### Rx1 · Medicines: safe reminders and advice
Status: [x] 2026-10-28
Depends on: F15a
From Erin's idea #48 (CRITICAL), 2026-10-28. "I don't remember if I took the wegovy or just
thought about taking it" got "Take it if you aren't sure". That's the wrong advice: a
missed dose is safer than a double one. **Erin asked that Michael check in with her before
this is built** (#52, Themi's task 40), so the details wait for that conversation.
- Themi never tells anyone to take a dose, or advises on doses at all. When someone isn't
  sure whether they took one, it says not to take another until they've checked, and to ask
  their doctor or pharmacist. Also in code: a medicine task's done check asks, and "not sure"
  never becomes done.
- General information (from the web, when that exists) always ends with "check with your
  doctor or pharmacist".
- Medicine tasks are marked as medicine, from the title or when said, and change nothing
  else about how they nudge.
- Scenarios from #48's own conversation.

Notes (2026-10-28):
- Michael confirmed the four points above after talking with Erin (task 40 done).
- Migration 0069: `tasks.medicine`, set at creation from the title's whole words
  (`tasks.MEDICINE`: pill, meds, medicine, medication, Wegovy, Ozempic, insulin, inhaler,
  tablet, capsule, prescription, dose, tab). Live tasks marked: Mimi pill (1 tab and 1/2
  tab) and Britney flea meds. `set_task_medicine` (schedules group) for "item 3 is my
  thyroid medicine".
- A medicine nudge ends "Taken already, or later?" with [Taken] [Not sure] [Later]. [Not
  sure] edits it to `NOT_SURE_TEXT` (no second dose until it's checked, or until the
  doctor or pharmacist says; it stays open) and changes nothing else. The morning list's
  ticks and the wall's ticks still count as done: they're a clear yes.
- `complete_task` on a medicine refuses when their message says they aren't sure (`UNSURE`:
  not sure, don't remember, maybe, might have, think I took...), telling the model what to
  say instead.
- The system prompt's medicine rule: never tell anyone to take a dose, no dose advice,
  unsure means no second dose until checked, general information ends "check with your
  doctor or pharmacist". The open items say ", medicine".
- Not done: Themi has no web lookup yet, so "general information" is only the model's own,
  under that rule. Re-run the evals with a medicine case when there's quota.
- The plan has a Medicines paragraph after the trust tiers (rev 201).
- Setup: restart (applies 0069).

### E2 · Email: an audit instead of single questions
Status: [x] 2026-10-28
Depends on: E1, T1
From Erin's idea #50, 2026-10-28: "Instead of individual emails, create an 'email audit' task
when it has emails that it's not sure about. Themi can prompt this audit, and if the user
accepts, then it goes through one by one and the user can select 'urgent' 'important' 'both'
or 'neither'. When all emails have been categorized, Themi gives a brief confirmation and ends
the email audit."
- Emails and senders triage isn't sure about wait in an audit, and E1's sender lists move
  into it. One task, "Email audit (5 to look at)", nudged like any other, in T1's order.
- Accepted: one email at a time (sender, subject, one line), with [Urgent] [Important]
  [Both] [Neither] and a way to stop partway. The answers teach triage about that sender,
  and E1's urgent senders come from them.
- At the end, a short confirmation ("All 5 sorted: 2 urgent, 1 important."), and the task
  closes.

Notes (2026-10-28):
- `themi.core.email_audit.EmailAudit`. Migration 0064: `email_audit_items` (a sender, or
  one email, with its answer) and `email_audits` (each person's task). E1's 17
  suggestions that were never answered moved in: 12 Erin's, 5 Michael's, reason
  "suggested before". A suggestion already added with an old message's button counts as
  settled.
- What goes in: E1's `email.senders` job puts its candidates in the audit instead of
  sending the list, then makes sure anyone with something waiting has the task. Triage
  has a new `unsure` field. An unsure urgent, noise or routine email gets no alert and no
  archive offer; it waits in the audit. Unsure replies, confirmations and receipts are
  acted on as before.
- The task is "Email audit (N to look at)", retitled as the count changes, a normal
  one-off task, so it's in T1's order and the one-at-a-time gate. Its nudge is its own,
  through a new hook (`TaskBoard.own_nudges`): "Email audit: N to look at, one at a time.
  Start now, or later?" with [Start] and the usual [Later] (a snooze).
- Each one: "1 of 5. Mail from SoFi (sofi@...), money." or "An email from X: subject" with
  triage's summary, then [Urgent] [Important] [Both] [Neither] [Stop for now]. An answer
  edits the question to "SoFi: urgent and important." and the next one comes. At the end:
  "All 5 sorted: 2 urgent, 1 important. That's the email audit done.", and the task is
  done. Stopping snoozes it for four hours.
- What answers do:
  - A sender: urgent or both adds it to the inbox's urgent senders (E1's `add`);
    important or both means its mail is never offered for archiving; neither means it's
    not asked about again.
  - An email: urgent or both files it as urgent; important takes it out of noise.
- `start_email_audit` (email group; "audit" now calls the group) for "let's do the email
  audit".
- Deviation: the idea's sliding scales aren't here; each answer is yes or no on each
  scale, as T1 has for tasks.
- Follow-ups: the task is a one-off, so it also shows on the wall's To-do list; ticking
  it there closes it without the audit. `keep_email`'s single "always urgent?" question
  (F15c) stays a message, since it answers what they just said.
- Setup: restart (applies 0064). The audit tasks appear at the next `email.senders` run
  (within 6 hours of the restart).

### E2b · Email audit: off the wall, and sliding scales
Status: [x] 2026-10-28
Depends on: E2
Michael's answers to E2's follow-ups, 2026-10-28: the audit task stays off the wall, and
yes to the sliding scales of Erin's idea #44 ("a sliding scale for each based on how
urgent or important the thing is").
- The audit task is Themi's own: never on the wall's to-do lists (ticking it there would
  close it without the audit).
- Each sender or email gets two questions: how urgent (not urgent, same day, right away),
  then how important (not important, somewhat, very). In words, never numbers.
- What the levels do: a sender that's urgent (same day) counts as urgent, as before; right
  away, its alerts always come at once. Somewhat important, its mail is never offered for
  archiving, as before; very, it's also never marked as read for them.

Notes (2026-10-28):
- Migration 0066: `tasks.off_wall` (set on the audit task; the wall's sync leaves such a
  task off the to-do lists and takes it off if it was already there), and
  `email_audit_items.urgency` and `.importance` (0-2, never shown; `answer` stays as the
  pair in short, for the closing count). Answers given before E2b become level 1.
- The flow: "1 of 5. Mail from SoFi (...), money.\nHow urgent is it?" with [Not urgent]
  [Same day] [Right away] [Stop for now]; the tap edits the same message to "How important
  is it?" with [Not important] [Somewhat] [Very] [Stop for now]; then "SoFi: urgent (same
  day), somewhat important." and the next one. Stopped between the two, it picks up at the
  second.
- Triage reads `EmailAudit.sender_levels`: right away makes the alert `urgent` priority
  even when the model didn't call it severe; very important leaves its confirmations
  unmarked. For a single email, the levels only file it, as in E2 (they're looking at it).
- Two taps per item instead of one. If that's too slow for a long audit, a [Same as
  before]-style shortcut is a possible follow-up.
- Setup: restart (applies 0066 with 0062-0065).

### P2a · Response timing, and a word while a reply is slow
Status: [x] 2026-10-28
Depends on: P1, F13
From Erin's ideas #51 ("make Themi faster") and #55 ("maintain internal metrics of why
responses take as long as they do"), 2026-10-28, and Michael's idea the same day.
Since 10-26, a conversation call on the free Gemini tier takes 9.8 s on average, 49 s at
most, and a reply often takes two or three calls.
- Per reply, a breakdown: each model call (seconds, waiting, retries), each tool, the
  outbox. Kept a week, like `ai_calls`, with the slowest replies and the medians on the
  admin website, so the slow part shows.
- Michael's idea: when a reply is still coming after 10 seconds, Themi sends one short
  message saying so. Some messages normalize what the family wants to be able to talk
  about: "I'm having a bit of a low-energy day myself, I'll answer as soon as I can."
  Others are plain: "Still thinking, nearly there." The rules:
  - At most one per reply, through the outbox as a reply. It doesn't count toward the limit.
  - Picked from a written list, varied, and not the same one twice in a row.
  - Gentle phrasing applies, and never an energy score.
  - Not for button taps or scheduled messages.
  - If the reply arrives in the moment the notice would go, the notice doesn't go.

Notes (2026-10-28):
- Split: the speed-ups are P2b, once there's a week of these numbers.
- `themi.core.timing`. Migration 0065: `replies` (each reply that went to the model: its
  whole time from the message arriving, the outbox's part, the "still coming" message if
  one went), `reply_tools` (each tool, and the model round that asked for it), and
  `ai_calls.reply_id` (set from `router.current_reply`). Kept a week.
- Admin page "Reply times" (`/ai/timing`, in the nav for admins): the week's count, the
  medians (in all, the model, tools, sending), and the ten slowest, step by step: each
  model round with its backend, wait and retries, the tools it asked for, any other call
  (a gentler rewording), then the outbox.
- The "still coming" message: eight written ones in `SLOW_NOTICES`, half of them about
  having a slow or low-energy day. It goes after 10 s (`SLOW_AFTER`), once per reply, as
  a reply (outside the daily limit), through the shield. Not for button taps, and never
  the same one twice in a row for a person (the last is read from `replies`). If the
  reply is ready when the 10 s are up, it doesn't go.
- `clock.sleep`: on a frozen clock it waits for the clock to be moved, so tests advance
  time instead of sleeping. `ScriptedProvider.take(seconds)` makes a chat call take that
  long.
- Not timed: a voice note's transcription is in the reply's whole time but isn't its own
  step. Quick yes/no answers (no model) aren't recorded.
- Setup: restart (applies 0065).

### P2b · Faster replies, from the numbers
Status: [ ]
Depends on: P2a, and a week of its timings
Split from P2 (2026-10-28): the speed-ups need P2a's numbers first.
- The speed-ups the numbers point to: a faster model for conversation, fewer tool
  rounds, smaller prompts (each call sends about 10,000 tokens, mostly tool schemas).

### P3 · Router metrics: how well the tool groups are chosen
Status: [x] 2026-10-29
Depends on: P1, P2a
From a talk about a "System 1" router (2026-10-29): should a fast classifier (embeddings or
a small model) choose the tool groups instead of P1's word lists? Not yet: first measure
how often the word lists miss and what a miss costs, and build a fair way to compare a
replacement. A router gets built only if these numbers ask for one.
Already measurable: a miss shows as a `more_tools` row in `reply_tools`, and its extra
model round is in `ai_calls`. Missing: which groups were offered, so over-sending (the
token side) can't be seen, and no way to score a candidate router without a model.
- Each `replies` row keeps the groups `choose_groups` offered at the start, and the groups
  `more_tools` added during the reply.
- The admin "Reply times" page (`/ai/timing`) shows the week's router numbers: replies
  with a miss (a `more_tools` call), the groups most often added late, the tools sent per
  reply (median), and the median time of replies with a miss and without one.
- An offline router eval: for each case in `tests/evals/cases.json`, run `choose_groups`
  over its message (and its history, if any) and check the groups of the tools in
  `expect`/`expect_any` were offered (recall), and count the tools sent (size). No model
  calls, so it runs in `make test-all`. It takes the router as a function, so a candidate
  can be scored the same way, and prints both numbers per category.
- No message text is kept for this. Keeping texts to replay later is the family's call;
  ask before adding it.

Tests: groups recorded on a reply, with and without `more_tools`; the page's numbers from
seeded rows; the offline eval scoring a known router (a perfect one, and one that misses a
group). Today's `choose_groups` recall goes in the Notes as the baseline.

Notes (2026-10-29):
- Migration 0072: `replies.groups` (the groups sent at the start, comma-separated, '' for
  the core only), `groups_added` (what `more_tools` brought in), `tools_sent` (tools with
  the first model call). NULL on older replies, which the numbers leave out.
  `ReplyTimer.route()` and `.added()`, called from `Agent._converse`.
- `themi.core.timing.router_numbers`; "Reply times" has a "Which tools went" section, and
  each of the slowest replies says which tools went ("Tools sent: 29 (core, lists), then
  pantry."). A miss is any `more_tools` call, even one that added nothing (it still costs
  a round).
- The offline eval is `tests/evals/routing.py` (`route_cases(registry, router, cases)`).
  It needs a built app's registry, since features register their tools on install, so it
  runs as `tests/scenarios/test_router_eval.py` with every fake (in `make test-all`).
  `make router-eval` prints the table. Only the message is routed, not the last four
  messages, so it's a little stricter than the live agent.
- Baseline (`choose_groups`, 2026-10-29): 51 of the 55 cases have their tools built; 12
  of them need a group beyond the core, and 11 got it (92%). Median 27 tools sent (22 for
  the core only, of about 70). `BASELINE_RECALL` holds it as a floor.
- The one miss: task-pause ("Please don't send me anything for the next couple of
  hours") gets no settings group; the words have "stop sending" but not "don't send". The
  real-model evals still pass it through `more_tools`. Left alone here (this prompt
  measures); a one-word fix for whoever picks it up.
- Only 12 cases test routing at all: too few to judge a candidate router on. More cases
  that need a group (paraphrases, the family's real wording) would help before comparing.
- Setup: restart (applies 0072). The live numbers fill in over the next week.

### P4 · Wrong actions: marked in chat, labelled in review
Status: [x] 2026-10-30
Depends on: P3, F1
From the router talk (2026-10-29): P3 sees only the misses the model notices itself (a
`more_tools` call). When Themi confidently does the wrong thing (olive oil on the
grocery list instead of the pantry), nothing ties it to the reply or the tool. Today those
turn up only as `/bug` reports, read by hand.
- **👎 on a reply marks it as wrong.** One tap on Themi's reply, never asked for: Themi
  doesn't ask "was that right?" and says nothing back. It doesn't change phrasing,
  approvals or energy.
- **Phrasing moves to the angry faces.** Decided 2026-10-29: 👎 comes out of
  `STRICTER_REACTIONS`, so 😠 😡 😤 😣 🙄 make phrasing gentler and 👎 no longer does,
  anywhere (on a nudge or summary it now does nothing until S5). The plan says only that
  reactions calibrate phrasing, so it doesn't change. The calibration module's docstring
  ("a 👎-style reaction") and its test move to 😠.
- `replies` needs to know its outbox messages (Telegram message ids), so a reaction finds
  its reply. A reaction on a message that isn't a model reply (a card, a nudge) is ignored
  for this.
- A marked reply keeps its row, tools and model calls past the week's clean-up, until it
  has been labelled.
- **`/bug` points at the reply.** The snapshot gains the reply it's about (the one it
  replies to in Telegram, else the latest), with its tools, groups offered and groups added.
- **Labelling, in review.** `themi feedback` lists marked replies with the snapshot's
  facts: the message, what Themi said, the tools it ran, the groups it offered. Then
  `themi feedback --wrong-tool <reply id> <tool>` (the tool it should have used; `none`
  for "no tool") or `--not-wrong <reply id>`. From the reply's offered groups, a label is
  saved as one of:
  - **router miss**: the right tool wasn't sent (its group wasn't chosen);
  - **model choice**: it was sent and the model used another;
  - **no tool needed**: it acted where it shouldn't have.
- The label prints a `cases.json` stub (id, category, the person's message, `expect`) to
  paste into the evals, so each real mistake becomes a case. The message comes from the
  stored conversation; nothing new is kept for it.
- "Reply times" (P3's section) adds the week's marked replies and the labels by kind, so
  the router misses and the model's choices can be told apart.
- Setup: tell the family before it ships that 👎 now means "that was the wrong thing" and
  an angry face means "too pushy".
- Not here: guessing mistakes from behaviour (an undo soon after, "no, I meant"). Too noisy
  for one family's numbers; revisit if the marks stay rare.

Tests: a reaction on a model reply marks it, on a card or nudge doesn't; the mark changes
no phrasing strength; a marked reply survives the clean-up until labelled; `/bug`'s
snapshot names its reply; 👎 no longer changes phrasing strength and 😠 still does; each
label kind decided from the offered groups; the case stub
loads with `load_cases`; the page's counts. A scenario: Erin reacts to a wrong grocery
add, and the review labels it a model choice.

Notes (2026-10-30):
- Migration 0078: `outbox.reply_id` (every message sent while a reply is written, from
  `router.current_reply`), and `replies.marked_at`, `label`, `right_tool`, `labelled_at`.
  The week's clean-up of `replies` (with `reply_tools`) and of `ai_calls` skips a marked
  reply until it's labelled.
- `themi.core.wrong_replies`:
    - `WrongReplies` is a reaction handler. A 👎 on a message whose outbox row has a reply,
      and isn't a card (approval, rule), marks that reply. Nothing is sent back.
    - `ReplyReview` works on the database alone, for the CLI. `decide()` uses the groups
      offered at the start and the ones `more_tools` added: a tool `more_tools` brought in
      was sent, so using another is a model choice. A twin set counts as sent whole (P6).
- Phrasing: 👎 is out of `STRICTER_REACTIONS`; 😠 😡 😤 😣 🙄 still make shielding stricter.
  S5's reactions skip a 👎 on a reply (a 👎 on a nudge or summary still counts there; 😕 on
  a reply too).
- `/bug`'s snapshot has `reply`: the reply that sent the message it replies to, else the
  latest. It holds the tools, the groups offered and the groups added; the report prints
  "About reply N".
- `themi feedback` lists unlabelled marked replies after the reports. `--wrong-tool <id>
  <tool|none>` and `--not-wrong <id>` label them, and a label prints a case stub
  (`review-<id>`, category `from_review`, `expect`, and `forbid` for the tools it used
  instead). The tool name isn't checked against the registry, since the CLI doesn't build
  the app.
- The person's message is the latest inbound message (not a reaction) at or before the
  reply's start.
- Reply times: "Marked wrong", with the week's count and labels.
- The prompt's example (olive oil on the grocery list instead of the pantry) can't happen
  any more: `add_to_grocery_list` refuses "used the last of". The scenario uses "remind me
  to buy olive oil tomorrow" put on the list instead of a task, labelled a model choice.
- Setup: restart (applies 0078), and tell the family that 👎 on a reply now means "that was
  the wrong thing", and an angry face means "too pushy".

### P5 · Evals that can compare: repeats, timings, and every tool vs groups
Status: [x] 2026-10-30
Depends on: P3
From the routing talk (2026-10-29): routing changes get decided by measurement. Today an
eval run gives one pass or fail per case, with no times, and one run of Gemini can't tell
a real change from noise (47/49 vs 46/49 means nothing on its own). And the cheapest
answer to "the word lists are fragile" hasn't been tried: send every tool and route nothing.
P1 grouped the tools because 55 tools were about 8,000 tokens a call on the free tier.
- **Repeats.** `make evals EVAL_ARGS='--repeat 3'` runs each case that many times. The
  summary gives each case's pass count (3/3, 2/3...), the pass rate per category and in
  all, and lists the flaky cases (passed some runs, not others) apart from the failing ones.
- **Timings per case.** Each result keeps its model calls, the seconds of each, and the
  tools sent with the first call (count and characters). The summary gives the medians.
- **Arms.** `--routing groups` (today) or `--routing all` (every tool on every call, no
  `more_tools` needed). The same switch is a setting, `TOOL_ROUTING` (default `groups`), so
  "all" can also be tried in the family's chat with P3's numbers watching it. `all` sends
  `ToolRegistry.specs()` and the agent leaves `more_tools` out.
- **A comparison.** `tests/evals/rescore.py` (or a small `compare.py`) reads two saved runs
  and prints, per case, both arms' pass counts, and in all: pass rate, median seconds per
  case, median model calls. Cases that pass every run in one arm and fail every run in the
  other are listed first: those are real differences, the rest is noise.
- **Decide before running.** Proposed rule (confirm or change it before the runs): `all`
  wins if its pass rate is no lower than `groups`' (within one case), no case goes from
  always passing to always failing, and its median reply is at most 20% slower. Then P7a and
  P7b aren't needed, and P1's word lists go (in a follow-up, after a week of `all` in chat).
- Run both arms, three repeats each, on the family's own model (Gemini flash-lite), and
  record the numbers and the decision in the Notes. The free tier's pacing makes this slow
  (`THEMI_EVAL_PACE`); run it in the background.

Tests: repeats aggregate (a case passing 2 of 3 is flaky, not failing); timings saved and
read back by `rescore`; `--routing all` sends every tool and no `more_tools`; the setting
does the same in a scenario; the comparison picks out always/never differences.

Notes (2026-10-30):
- The rule was agreed as proposed (2026-10-29). It's written into
  `tests/evals/compare.py`, which prints the verdict.
- `THEMI_TOOL_ROUTING` (`Settings.tool_routing`, `Services.tool_routing`, `build_app`,
  the scenario harness): `all` sends `ToolRegistry.specs_for(groups, "all")`, every tool
  but `more_tools`. P3 records every group as sent, so its numbers still read right.
- Evals: `--repeat N` and `--routing groups|all` (parametrized in `tests/evals/conftest.py`,
  ids `case-run2`). Each result keeps `run`, `model_seconds` (real clock, less the
  limiter's waits: `MinuteLimiter.waited`), `tools_sent` and `tools_chars` (first
  conversation call). Results are named `<provider>-<routing>-<stamp>.json`. The summary
  adds the medians and the flaky cases; `rescore.load_run` reads it all back.
- Evals read only `GEMINI_TEST_API_KEY` (env or `.env`) and skip without it; the family's
  `GEMINI_API_KEY` sits in the same `.env` and was used by mistake for about 10 requests
  before this. The summary also prints "Failed every run:".
- Runs (2026-10-30, 3 repeats each). Groups on gemini-3.5-flash-lite (fallback 3.1):
  142/150, median 2.9 s and 24 tools a case. 3.5's free daily quota then ran out, so both
  arms went again on gemini-3.1-flash-lite, no fallback. Groups: 142/150 (94.7%), median
  2.2 s, 24 tools (16,712 characters). All: 49 tools (29,546 characters); its quota ran
  out after 15 of 55 cases.
- Compared on the 13 cases both arms ran fully (energy notes and pantry):
  groups 39/39 runs, all 35/39; median 3.0 s vs 2.0 s. No case flipped always/never;
  all lost runs on pantry-add-cumin (1/3: said "I've added" with the pantry tools also
  in reach), energy-husband and energy-meetings (2/3 each). **Verdict: groups stays**
  (all passes more than one case fewer). Sending every tool wasn't slower, so size isn't
  the cost; choosing among near-twins is, which is P6's job. P7a/P7b stay on.
- Confirmed on the full set (2026-10-30), every tool on gemini-3.5-flash-lite (fallback
  3.1) against the groups run above: all 137/150 (91.3%) vs groups 142/150; mean cases
  passed 45.7 vs 47.3 of 50; median 2.4 s vs 2.9 s. Always passed with groups, always
  failed with every tool: energy-husband (no energy note), rule-husband-groceries and
  rule-thinking-aloud (create_task, and set_task_schedule, picked over propose_rule).
  The other way: energy-medium-day and task-have-partner-do-it. **Groups stays** on both
  models. The losses are rule vs task, a near-twin pair: P6.
- Seen in passing, not P5's: task-have-partner-do-it fails 3/3 on both models because the
  prompt's example names "Michael" (prompts.py, "can you have Michael get the pacifier")
  and the eval family's husband is "Husband", so the model copies the example. Reword the
  examples to "my husband". energy-medium-day's `show_lists` call is reasonable; the case
  could allow it.

### P6 · Near-twin tools: sent together, told apart, tested both ways
Status: [x] 2026-10-30
Depends on: P5
From the routing talk (2026-10-29). Some tools sound alike and do very different things,
so they stay separate tools; the work is making sure the model sees both and can tell them
apart. Today each description already names its twin ("Not for 'don't send me anything':
that's pause_messages"), but the twins don't always travel together: in the 2026-10-29
evals `add_to_grocery_list` (core) was sent without `update_pantry` (pantry group), and the
model used the twin it had. Nothing in the routing knows they belong together.
- **A second tier: twin sets.** `TWINS` in `themi.core.tools`, each a named set of tools
  the model confuses, with one short paragraph on how to tell them apart. A starting list
  (check each against what the tools really do, and add any the evals or P4 find):
  - *food and buying*: `update_pantry` (what the house has: used up, low, bought),
    `add_to_grocery_list` (food to buy, when they ask for the list), `add_to_things_to_buy`
    (non-food to buy), `add_to_list` (a named list).
  - *quiet time*: `start_break` (the person is resting: nudges and check-ins wait, then one
    question when it's over), `pause_messages` (hold one kind of message for a while).
  - *rules or tasks*: `propose_rule` (how Themi itself behaves), `create_task` (something
    to do, once or repeating), `set_task_schedule` (when a task repeats).
- **Sent together.** If any tool of a twin set is sent, all of it is, whatever the router
  chose (in `ToolRegistry.specs`, so every arm of P5 and any later router get it free).
  Because grocery and task tools are core, this pulls `update_pantry`,
  `add_to_things_to_buy`, `add_to_list`, `start_break`, `pause_messages` and
  `set_task_schedule` into every call: P3's "tools sent" shows the cost.
- **Told apart once.** The set's paragraph goes in the system prompt whenever the set is
  sent ("Food and buying: ..."), with a pair of examples each way. The descriptions keep
  what each tool does and drop the long cross-references the paragraph now covers.
- **Behaviour that differs.** Where the words leave no doubt, a tool may decline in favour
  of its twin, the way `propose_rule` already declines "remind me to" (only on the person's
  own words, never the model's, and only for wordings a case covers).
- **Cases both ways.** A "twins" category in `cases.json`: for each set, at least two cases
  per tool that need that tool and forbid its twins, and one or two truly ambiguous ones
  ("out of milk") that allow either. Run P5's harness (3 repeats) before any change, then
  after: the Notes give both.

Tests: a twin set is sent whole when any member is; the paragraph is in the system prompt
only with its set; each declining tool declines only the covered wording; the twins cases
load and their tools exist.

Notes (2026-10-30):
- `TWINS` in `themi.core.tools`: food and buying (`update_pantry`, `add_to_grocery_list`,
  `add_to_things_to_buy`, `add_to_list`), quiet time (`start_break`, `pause_messages`),
  rules or tasks (`propose_rule`, `create_task`, `set_task_schedule`). `ToolRegistry.specs`
  sends a set whole; the agent adds `twins_text(...)` for the sets sent to each call's
  system prompt. Food and rules ride on core tools, so they go on every call; quiet time
  goes with the settings group. The STABLE_SYSTEM bullets and description cross-references
  they replace are gone.
- Declines, on the person's words only: `create_task` for "new rule" / "make it a rule"
  (not with "remind"); `add_to_grocery_list` for "running low", "used the last",
  "finished the"... unless they also ask for the list ("out of milk" stays either);
  `start_break` for "don't send me", "hold the..." unless they say break, rest or lie down.
  The evals still count a declined call against the case: they score the first choice.
- The examples that named "Michael" (create_task, the prompt) now say "my husband".
- Evals, gemini-3.1-flash-lite, 3 repeats. Twins (22 cases): before 52/66, after 57/66;
  twin-pantry-finished went 0/3 to 3/3, twin-pantry-low-coffee and twin-task-husband-door
  2/3 to 3/3, nothing worse (`gemini-groups-20261030-0810` vs `-0825`). The other cases,
  against 2026-10-29's 3.1 run on the 36 both finished (quota ran out in tasks): 35/36 vs
  35/36, no flips. Tools sent per call, median: 24 to 27.
- Median model seconds went 2.2 to 3.8 on those 36 cases, but the twins runs went 6.4 to
  2.6 the other way with more tools, so run-to-run timing on the free tier swamps it.
  P3's timing page will show the real cost in the family's chat.
- Still failing every run: twin-pause-meals, twin-pause-tonight, twin-break-lie-down.
  "hold the meal reminders", "don't send me" and "lie down" don't bring the settings
  group, so neither quiet-time twin is sent and the model reaches for propose_rule. That's
  routing (P7a/P7b), not telling twins apart. `make router-eval`'s baseline is now 21/25
  with the twins cases in.
- Follow-up: run the task and email cases after P6 on a fresh day's quota.

### P7a · Routing data: the family's kinds of message, labelled
Status: [x] 2026-10-30
Depends on: P3, P5 (only if P5 keeps routing)
The router eval (P3) has 12 cases that need a group: too few to compare routers on. An
embedding router also needs example phrases per group, kept apart from the cases it's
scored on.
- **Routing cases**, about 80 to 100, in a new `tests/evals/routing_cases.json`: a message
  (and the message before it, for follow-ups like "and limes") and the groups it needs.
  Drafted from the kinds of thing the family says, read from the stored conversation, but
  written as paraphrases: no names, places, health or money details from their messages go
  in the repo. Each group gets plain cases, paraphrases, short follow-ups, and messages
  with two asks ("add milk and remind me Tuesday" needs both).
- The labels are checked by a person before they count: print them for review, and only
  reviewed cases go in the file.
- **Group examples**, 10 to 20 per group, in `themi.core.tools` beside `GROUPS` (they ship
  with Themi), none copied from the routing cases.
- P3's eval reads both case files. Today's word lists get scored on the new set; the
  Notes give the new baseline.
- Later, P4's labels add to both: a "router miss" becomes a case, and (paraphrased) an
  example for the group that was missing.

Tests: both files load, every group named exists, no example is also a case, every group
has examples and cases.

Notes (2026-10-30):
- `tests/evals/routing_cases.json`: 93 cases (46 plain, 23 paraphrase, 13 follow-up with
  the message before, 11 two-asks), drafted from the kinds of thing in the family's chat
  (353 messages read locally) and paraphrased: no names, places, health or money details
  of theirs. Reviewed by the user, 2026-10-30.
- Deviation: a case names the *tools* it needs (`tools`, or `any_of` for either), and the
  groups follow from `TOOL_GROUPS`. Labels survive a tool moving group, and recall counts
  tools a twin set (P6) brings along.
- `GROUP_EXAMPLES` in `themi.core.tools`: 12 per group, written fresh; a test checks none
  is a case.
- `tests/evals/routing.py` reads both files (`Routable`, `load_routing_cases`); a router
  gets the message and the one before it.
- Word lists, new baseline: 74/84 on the routing cases (plain 36/37, paraphrase 14/23,
  follow-up 13/13, two-asks 11/11), 95/109 with the eval cases; median 33 tools sent.
  Misses are mostly paraphrases: "lie down", "need a nap", "hold the meal reminders",
  "turn the laundry nudges back on", "it came to $35", "when could I fit in...".

### P7b · An embedding router, if P5 says routing stays
Status: [x] 2026-10-30
Depends on: P7a
Embeddings instead of word lists: no training, just nearest neighbours. Each group's
examples become vectors once; each message becomes a vector; every group with an example
close enough is sent.
- `themi.ai.embeddings`: an `Embedder` interface (texts in, vectors out). First version:
  Gemini's embedding API through `themi.ai.router` (a new `AITask.EMBEDDING`, so per-member
  keys, retries and fallback apply). A local model can replace it later; note that the
  usual local runtime (onnxruntime) has no wheel for Python 3.15, which the dev venv runs
  (Docker is 3.13). A fake embedder in `tests/fakes`, so tests make no network calls.
- The examples' vectors are cached (keyed by model and text), so a restart doesn't embed
  them again.
- `choose_groups` adds the embedding pass to the word lists at first (a union, so recall
  can only rise), over this message and the last few. Every group above the threshold, not
  just the best, so two asks bring two groups. If the embedding call fails or is slow (over
  a second), the word lists alone decide: routing never costs a reply. `more_tools` stays.
- Groups recently used (a tool from it ran in the last few turns) stay sent: short
  follow-ups carry too little for either method.
- The threshold is chosen with P3's eval on P7a's cases: print recall and tools sent at
  several thresholds, pick the lowest tool count with recall at or near 100%, and say why in
  the Notes.
- A setting turns it on. After a week with it on, P3's live numbers ("needed more tools",
  tools sent) against the word lists' week decide whether the word lists go.

Tests: the fake embedder routes paraphrases the word lists miss; two asks bring two groups;
a failing or slow embedder falls back to the word lists; recently used groups stay; the
cache is reused across restarts; the routing goes through the router (keys, fallback).

Notes (2026-10-30):
- Providers gained `embed` (Gemini; Claude and OpenAI-compatible say they can't, so the
  router skips them). `AITask.EMBEDDING` routes it, so keys, retries, fallback and the
  `ai_calls` record apply. Migration 0073 rebuilds `ai_routes` (its CHECK listed the tasks)
  and gives each member an embedding route on the Gemini backends of their conversation
  chain, model `gemini-embedding-2` at 768 dimensions (it told "lie down" from "oat milk"
  further apart than -001 did). Gemini-embedding-2 wants one Content per text.
- `themi.ai.embeddings` (`Embedder`, `RouterEmbedder`, `VectorCache`) and
  `themi.core.routing` (`EmbeddingRouter`, `recent_groups`). With
  `THEMI_TOOL_ROUTING=embeddings` the agent sends the word lists' groups, plus every group
  with an example at least 0.725 similar to this message, the person's last two, or any of
  their clauses (one vector of "need a nap, then what's for dinner?" sits between the two),
  plus the groups whose tools ran in their last 3 replies. Over a second, or on any
  failure, the word lists decide alone; the examples keep warming in the background.
- Threshold (`tests/evals/test_router_thresholds.py`, 166 cases): word lists alone 95/109,
  median 33 tools. With embeddings at 0.725: 108/109, still 33 tools; 0.7 is the same
  recall at 36 tools, 0.75 loses one more case. The one miss: "Nothing from the
  neighborhood app is ever urgent". Embeddings alone need 0.675 for 99% (38 tools), so
  the union stays. Each group's examples sit about 0.63 to 0.69 from each other.
- The free tier counts each embedded text as a request (100 a minute): the 108 examples
  spill into a second minute once per model (the router's retries wait it out), and recent
  message vectors stay in memory (never stored) so the last two messages aren't embedded
  again.
- Not done: a behaviour eval run with `--routing embeddings` (both models' quotas were
  spent today); it's wired (`make evals EVAL_ARGS='--routing embeddings'`).
- Setup for the family: `THEMI_TOOL_ROUTING=embeddings` in `.env`, and a Gemini backend in
  each person's conversation chain (or an embedding route on the website). Then a week of
  P3's numbers against the word lists' week decides whether the word lists go.

### F16a · Feedback (2026-10-28): automatic is per person
Status: [x] 2026-10-28
Depends on: 11, 13, F2
From Erin's bug #58 and Michael's idea #62, 2026-10-28.
- #58 ("Themi has been archiving my emails"): Michael turned on "Archive noise emails" as
  automatic on the website (rule 17, 27 Oct). The category's tier is household-wide, so
  Erin's noise was archived without a question 11 times until he turned it off (28 Oct,
  09:28). #62: "automating things like archiving email should be done on a per user basis,
  not a household one."
- The plan's trust tiers don't say whose actions a grant covers. Now: a category whose
  scope is `member` (each person's own email, calendar, routines) becomes automatic per
  person, and only for the person who locked the rule. A `family` category (the grocery
  list, the family calendar, Themi's lists) stays household-wide, admins only.
- A person makes their own categories automatic, admin or not (it's their own mail). The
  rule says whose it is ("Automatic for Erin: archive noise emails") and is a personal rule
  (F2), so it is only in that person's conversations.
- The website's "What Themi does on its own" shows, for a member category, the viewer's own
  setting with their own switch, and who else has it automatic. Tier 3 (an anomaly) still
  pauses the whole category for everyone.
- Migration: a member category that is automatic now becomes automatic for the person whose
  rule granted it, and no one else.
- Tests: Michael's grant leaves Erin asked; Erin's own grant; a non-admin can't grant a
  family category; unlocking undoes only that person's; the migration; a scenario from #58.
- Plan: the trust tiers section gets a sentence on whose actions a grant covers.

Notes (2026-10-28):
- Migration 0067: `member_tiers` (category, member, the granting rule). A trigger refuses a
  capped or household category there. A member category that was automatic moved to its
  rule's person; `action_categories.tier` is now only for household categories. Locked
  grants of member categories became personal rules. The live data had none (rule 17 was
  already unlocked).
- `Autonomy.grant_tier2(name, via_rule_id, by, member=None)`: a household category needs
  an admin, as before. A personal one is only ever for `by` themselves. `revoke_tier2` is
  theirs, or an admin's for anyone's. `granted(name, member)` (ignores a Tier 3 pause),
  `is_automatic(name, member)` (what `stage` uses) and `granted_to(name)`. Escalation
  still pauses the whole category for everyone, and only an admin resumes it.
- Rules: an `autonomy_grant` takes its category's scope whatever `applies_to` says; a
  member's own needs no admin. `grant_automatic` writes "Automatic for Erin: Archive noise
  emails". `revoke_automatic(by, category, whose=None)`.
- Website "What Themi does on its own": a personal category shows "For you: asks
  first/automatic", who else has it, and [Make automatic for me] for anyone. Shared
  categories stay admin-only.
- K3's offer to add events from booking emails is now per person ("Add events from my
  booking emails to my calendar without asking"), and asked of each person once.
- The plan's trust tiers paragraph says this (rev 197).
- Setup: restart (applies 0067). Anyone who wants automatic archiving turns it on for
  themselves on the website.

### F16b · Feedback (2026-10-28): noise emails in one message, inside the limit
Status: [x] 2026-10-28
Depends on: F16a, E2, F15b
From Michael's idea #61, Erin's idea #63 and Michael's bug #66, 2026-10-28.
- #61: "email archive messages come in too frequently. We should bundle many archive
  requests together on the site (archive all button), and make sure ... the message limit"
  is respected. #63: "by default, non urgent emails should be batched into a single message
  (default up to once daily, though the frequency should be user customizable) for bulk
  archiving." #66: of the ten archive cards Michael got on the afternoon of 28 Oct (his
  daily limit is 3), only one email was still in his inbox.
- Noise isn't asked about one at a time. Offers to archive wait, without a card, and come
  together in one message: "6 emails look like noise:" with a line each (sender: subject),
  and [Archive all] [Not now], plus a pointer to the website to pick.
- When: each person's setting, "once a day" by default at 6 pm, or twice a day (noon and
  6 pm), or every other day. It's a normal message: the daily limit, quiet hours and
  pauses hold it like any other. Nothing to offer, no message.
- Before the message goes, each email is checked in Gmail: one that is no longer in the inbox
  (archived, deleted, filed by hand) is dropped and its offer closed quietly. Gmail can't
  be reached: they're listed anyway.
- [Archive all] archives them all and edits the message to say so ("Archived 6."). [Not now]
  leaves them for the next one. An answered offer leaves the list.
- Website: "Emails to archive" lists each person's own offers with a checkbox each,
  [Archive all], [Archive the ticked ones] and [Keep the ticked ones] (keeping one is a
  decline). Linked from the dashboard when something is waiting.
- Automatic (F16a) still archives at once; this only changes how the asking is done.
- Tests: no card per email; the digest at the time, with its count; the setting; the daily
  limit holds it; emails gone from the inbox are left out; archive all; the website
  page; a scenario from #66.

Notes (2026-10-28):
- Michael confirmed (2026-10-28): once a day at 6 pm by default, twice a day or every other
  day as the options; "the one at a time thing" in #66 is the per-email archive cards.
- `themi.core.noise_digest.NoiseDigest` (`services.noise`, job `email.noise` every 5
  minutes). Migration 0068: `members.noise_emails` ('daily', 'twice', 'every_other_day')
  and `noise_digests` (each message, the offers it listed, the answer).
- `ApprovalsUI.held`: a category another module asks about. It gets no card, isn't
  re-asked when a snooze ends, and isn't a bare "yes" target. It's still in /pending.
- The message: "2 emails look like noise:\n- Shop: 20% off\n- ...\nArchive them all? ..."
  (15 lines at most, then "and N more"), [Archive all] [Not now], a normal message with no
  deadline, so the daily limit and quiet hours hold it. A newer one replaces one still
  queued. Archive all (or a bare "yes" while it's the latest) edits it to "Archived N."; Not
  now to "Left for now. They'll be in the next one."
- Before it goes, each email is fetched from Gmail: no longer in INBOX (or gone), its
  offer is withdrawn ("Already out of the inbox."). A Gmail error lists it anyway.
- Times are fixed (noon, 6 pm); a missed time (Themi down) is caught up within 3 hours.
  Every other day counts days since the last message.
- Website: "Emails to archive" (`/email/noise`, `themi.web.email_pages`) with Archive all,
  Archive the ticked ones, Keep the ticked ones (a decline). The dashboard shows one link
  instead of a card per email. The setting is under My settings, "My email".
- Offers still lapse after 3 days unanswered (APPROVAL_TTL), so every-other-day messages
  can't pile up. The plan's triage bullet says this (rev 198).
- Setup: restart (applies 0068). The first message goes at 6 pm with whatever is waiting.

### F16c · Feedback (2026-10-28): time-sensitive, explaining email levels, the run, slow notices
Status: [x] 2026-10-28
Depends on: E2b, F15c, F9a, P2a
From Erin's ideas #59, #60 and #65 and bug #64, 2026-10-28.
- #60: "Urgent as a label feels unnecessarily rushed. I would replace urgent with 'time
  sensitive' for routine use, and reserve urgent for things that truly need to be dealt
  with soon." Everything a person reads says "time-sensitive" for what E2b calls urgent
  (same day): normal alerts ("An email that looks time-sensitive ..."), the audit's
  buttons ([No rush] [Time-sensitive] [Urgent]), the senders' setting, and replies.
  "Urgent" is kept for right away: an alert that interrupts. The stored levels and the
  task levels (T1) don't change.
- #59 ("Brevity is good, clarity is better"): asked "set similar emails to medium urgency
  and medium importance", Themi offered "always urgent", then explained urgent as "appear at
  the top of your inbox or in your daily digest" (neither exists). The model gets what the
  levels really do, in a few plain lines, and a tool sets a sender's two levels in words
  (`set_sender_levels`), the same as the audit's answers. Its explanation is said in full.
  Also: `keep_email` failed when the sender had been offered before (UNIQUE on
  `sender_suggestions`); it reuses that row.
- #64 ("I ran yesterday, and this logic on the run spacing is wrong"): the run was recorded
  done on Tue 27 Oct and is due Thu 29 Oct, but Themi said "Saturday ... Tuesday was
  missed", with no tool called. The open items give a repeating task's next day with its
  weekday and when it was last done ("next Thu 29 Oct; last done Tue 27 Oct"), and a
  calendar card for a time that's past lapses (the Tue run card from before F15b).
- #65: "increase the required delay for a 'sorry this is slow' message." 10 s → 25 s.

Notes (2026-10-28):
- #60, the words: an email alert says "time-sensitive" unless it comes at once (severe, or
  a sender set to urgent), then "urgent". The audit asks "How soon does it need you?" with
  [No rush] [Time-sensitive] [Urgent], and reads back "time-sensitive" ("All 5 sorted: 2
  time-sensitive, 1 important."). E1's offers, `keep_email`'s question and button ("Always
  time-sensitive: ..."), `set_urgent_senders`, `inbox_setup` and the website's inbox
  setting say time-sensitive too. Stored values, column names and the task levels (T1)
  are unchanged.
- #59: `set_sender_levels(sender, urgency, importance)` (email group). It finds the
  sender from their words (`triage.find_email`, now public), records the levels as an
  answered audit item ("said in chat"), and keeps the inbox's time-sensitive senders in
  step (time-sensitive or urgent adds the address; no rush takes off that exact address,
  never a domain). Its result and `inbox_setup`'s end with `LEVELS_TEXT`: what each level
  really does, and that nothing in Gmail is moved or highlighted. A system prompt line:
  asked what something means or why, explain it fully from what the tools say.
- The `keep_email` crash: a sender already in `sender_suggestions` is reused.
- #64: a task's open-items line gives the due day with its weekday ("due Thu 29 Oct"), and
  a repeating task's "Last done Tue 27 Oct." `Proposal.expires` (staged tools):
  `block_time_for_task` and `find_time_for_task` cards lapse when the block's time has
  passed. The stale card in #64 came from before this.
- #65: `SLOW_AFTER` is 25 s. The timing tests take their times from it.
- Not done: #59's "brevity vs clarity" is a prompt line only; re-run the evals when there's
  quota. The plan's triage bullet says time-sensitive vs urgent (rev 199).
- Setup: restart. No migration.

### F16d · Feedback (2026-10-28): only Gmail's Primary inbox counts
Status: [x] 2026-10-28
Depends on: F16b
The rest of Michael's bug #66 ("only the email about Apple IDs is even in my inbox"). After
the restart, F16b's first message for him listed 18 emails that Gmail still marks INBOX:
17 in the Promotions tab and 2 in Updates. Michael, 2026-10-28: "Definitely Gmail's primary
inbox is the only one that counts."
- In the inbox means Primary: labelled INBOX and none of CATEGORY_PROMOTIONS,
  CATEGORY_UPDATES, CATEGORY_SOCIAL or CATEGORY_FORUMS. For everyone.
- Triage doesn't offer to archive noise that isn't in Primary (Gmail has already put it
  aside). Alerts are unchanged.
- The noise message checks each email's labels in Gmail as it's made, and leaves out (and
  closes) any not in Primary.
- A message still waiting to go out (the daily limit held it) is made again, at most once
  an hour, so what it lists stays true until it goes.
- Tests: tab mail isn't offered; an offer whose email moved to a tab is dropped; a held
  message is rebuilt; a scenario from #66.

Notes (2026-10-28):
- `themi.connectors.gmail.parse.in_primary(labels)`: INBOX and none of `TABS`. Triage
  reads the labels stored at sync; the noise message reads them fresh from Gmail.
- `NoiseDigest._stale`: the latest message is still queued, unanswered, and over an hour
  old (`REBUILD_AFTER`), so the 5-minute job makes it again (cancelling the queued one).
- Found live: of Michael's 19 waiting offers, 17 were in Promotions and 2 in Updates. The
  messages queued for 8 am on 29 Oct are rebuilt within an hour of the restart, and those
  offers are withdrawn ("Already out of the inbox.").
- Alerts still come for time-sensitive mail in any tab; only archiving changed.
- The plan's triage bullet says Primary (rev 200).
- Setup: restart. No migration.

### F17a · Feedback (2026-10-28): noise to archive in chat, the audit's subject and link, tasks by name
Status: [x] 2026-10-28
Depends on: F16d, E2b
From the family's reports of 2026-10-28 evening: Michael's bug #67, Erin's idea #69 and bug
#71. F17b takes #68 and #70.
- #67 ("noisy emails that were on the site to be archived didn't appear when asking about
  them in telegram"): asked "Are there any messages to mark read or archive?", Themi listed
  only the two "waiting on you" items; the 18 noise offers were only in a queued message,
  cut off at 80 characters. The open items list the noise offers still waiting (sender and
  subject, a few, then a count), and a tool archives them, or keeps them, from chat
  (`archive_noise_emails`, all or the ones they name), through the same approvals as the
  [Archive all] button. "archive", "noise" and "mark as read" call for the email tools.
- #69 ("email audits should have an exact subject for each email and a link to the email
  being referenced"): asked for the subject twice, the model made one up ("or similar"). An
  audit item about a sender shows its latest email's exact subject; every item has a Gmail
  link to that email.
- #71 ("it's displaying tasks by number instead of by name"): "Task 50 is taken off the
  list." The system prompt says to call tasks by their names, never their numbers, and a
  reply that still says "task 50" gets the task's name in its place.
- Tests: the open item and the tool (all, by name, keep, nothing waiting), the email words;
  the audit's subject and link; the reply guard; a scenario from #67 and one from #71.

Notes (2026-10-28):
- #67: `NoiseDigest.open_items`: "Emails that look like noise, N waiting for a yes to
  archive", the first 10 as "Sender: subject" inside a `<data>` block (they're email text).
  `archive_noise_emails(answer, which)` (email group) archives or keeps them through
  `approvals.resolve`, as the button does; `which` matches words in the sender or subject,
  empty for all. Afterwards a digest still queued is made again, or taken back when
  nothing's left (`NoiseDigest.refresh`). The email group's words add archive, noise,
  junk, spam and "mark as read".
- #69: an audit card about a sender adds `Latest: "<subject>"` (its newest email in that
  inbox), and every card ends with a Gmail link (`gmail.parse.web_link`, which spending's
  receipt links use too). The card is sent without a link preview; the second question is
  an edit, which Telegram may preview. The model still never sees the audit's emails.
- #71: a system prompt line (tasks by name, never number), and `agent._by_name` puts the
  name, in quotes, in place of "task 50" (or "task 7 (Clean the bird cage)") in a reply.
  The PDA shield now leaves a sentence that opens with a quote alone: '"Refill the water"
  is off the list' was becoming "Up next: ...".
- Not done: #67's model reply also called a reply draft "to mark as read"; the clearer open
  item should help, re-run the evals when there's quota.
- The plan's triage bullet says noise can be archived or kept from chat (rev 202).
- Feedback #35-#57 were handled by earlier prompts but never marked reviewed; #33 and #34
  still wait for Erin's spec. Marked reviewed now: #35-#57 and #67, #69, #71.
- Setup: restart. No migration.

### F17b · Feedback (2026-10-28): which list, and a reminder after a task is done
Status: [x] 2026-10-28
Depends on: F17a
From Erin's idea #68 and bug #70, 2026-10-28.
- #68 ("if an item could be added to more than one list, provide a prompt with buttons for
  the most likely options plus 'not now'"): "paper towels" was staged for the grocery list;
  she meant Things to Buy. When an item could go on more than one list, one card asks
  which, with a button per likely list and [Not now]; the tap adds it there.
- #70 ("Immediately after I indicate that I cleaned the bird cage, remind me to refill the
  water and replace the food bowls" became a task due the next day, and its date read back
  as "2020"; "make this work"): a task can follow another: it waits, with no date, until
  that one is done, then its nudge goes at once (inside quiet hours and the limit). A
  repeating task's follower comes back each round. Dates the model reads carry the year
  where it isn't this year, and replies about a date use the context's year.
- Tests: the list card and its buttons; a follower waiting, then nudged when the first is
  done, each round; scenarios from #68 and #70.

Notes (2026-10-28):
- #68: `themi.core.which_list`: `ask_which_list(item, lists)` (core) sends "Paper towels:
  which list?" with a button per list (at most three; "grocery list", Things to Buy, or a
  named list) and [Not now]. A tap stages the add as asked for (`requested=True`), with
  the list's own executor (Things to Buy's remembers it isn't food), so the tiers still
  decide; the card is edited to the result. One list only is refused. The system prompt,
  `add_to_things_to_buy` and the grocery/Things to Buy refusals point to it instead of
  "ask".
- #70: deviation from the prompt: a follow-up isn't a waiting task (a new task status
  would touch every open-task query, the wall sync and nudges). Migration 0070,
  `task_follow_ups`: `add_follow_up(after_task_id, title, steps)` and `remove_follow_up`
  (core). `TaskBoard.done_hooks` run each time a task is done (each round too, from chat,
  a button or the wall); `FollowUps.on_done` makes a task due today, off the wall, and
  nudges it (as a reply when they did it in the chat, else normal). Not a second while
  the last one is still open. A one-off's follow-up goes after once; a cancelled task's
  goes. The open items say 'Follow-up: once "X" is done, "Y" comes up straight away'.
- #70's "2020": open items give a task's due day with a year only when it isn't this
  year (`tasks._day_words`), and the system prompt says dates are the local time's year,
  said without one.
- The live task 50 (Erin's refill) was cancelled already (#71), so she'll need to ask
  again; the follow-up will take it now.
- Evals (2026-10-29, Gemini 3.5 flash-lite): new cases for #68, #70, #71 and Rx1 pass.
  The full run was 34/45, 37/45 once scoring allows `more_tools` (P1's, which changes
  nothing). Found by them and fixed: names said bare ("Book the vet appointment is marked
  done.") read as orders, so the prompt says names go in quotes; and the follow-up's
  "straight away" read as pressure, now "as soon as ... is done". Still failing, older:
  pantry-olive-oil and pantry-bought (grocery list, not update_pantry), rule-bins
  (propose_rule, not a task), task-pause (start_break, not pause_messages; B1 made that
  ambiguous), energy-plumber, pantry-spinach-expiry.
- Evals, second pass (2026-10-29): 44/47 full, then the last 3 fixed and passing (6/6
  re-run), PDA-safe 100%. Fixes: the pantry group's words take "used the last of",
  "picked up", "using up" and the like, the schedules group's "always", "remind" and
  "Tuesdays"/"evenings" (without them the model had no update_pantry or set_task_schedule);
  `propose_rule` refuses "remind me about/to" (a task); "don't send me anything" is
  pause_messages, not start_break; `suggest_meals` only when asked; `create_task` reads
  "someone else" as the other partner; energy is logged first; `draft_vendor_call`
  refuses a text; "remember that X" is a fact, a chore only when they ask to be
  reminded. The evals give a case the fake Gmail when its setup needs it (`noise`), with
  two cases from #67, both passing. Scoring counts `more_tools` as read-only.
- Found while running them: 25 scripts in `.venv/bin` had a shebang into a
  `working-memory` checkout that no longer exists (so `.venv/bin/pytest` couldn't start);
  rewritten to this venv's python.
- The plan's task matching bullet has follow-ups and the which-list card (rev 203).
- Setup: restart (applies 0070).

### F18a · Feedback (2026-10-29): the wrong event moved, honest staging, a task for the other partner, "too tired"
Status: [x] 2026-10-29
Depends on: F17b, K3
From the family's reports of 2026-10-28/29: Erin's bugs #72, #73, #81 and #82.
- #73 ("it rescheduled the wrong event"): "When is my next run scheduled?" then "Let's move
  that up to 12pm so that there's plenty of time before tutoring" staged moving "Tutor
  Gabriel" to 12-1:20 pm. The run is a repeating task (task 8, 2 pm), so the move belongs
  to the task's time, not a calendar event; `move_calendar_event` takes an event only when
  its title matches what they named. The reply also said "Tutor Gabriel is moved" while the
  move waited for a yes: a staged change is said as staged.
- #81 ("it's still trying to move my tutoring"): the move she declined with [Not now] came
  back at 08:00, after she had approved moving that event to 4 pm. A staged calendar move is
  dropped when the same event has since been moved, or another move of it is staged.
- #82 ("I thought we implemented this feature already?"): "Can you have Michael get the
  pacifier under the couch foot ottoman thing?" got "Themi can't pass messages between
  people yet." Asking Themi to have the other partner do something is a task for them
  (`create_task`, as "someone else"), not a relay; only "tell/let X know/message X" is.
- #72 ("this seems wrong"): "I'm too tired tonight" got "Dryer now, or later tomorrow?",
  the system prompt's example line, with no dryer task. The reply acknowledges it and offers
  to let tonight's open items wait; examples in the prompt are marked as examples.
- Tests: the move matched to a task vs an event; a stale staged move dropped; the staged
  reply's wording; "have X do Y" as a task; scenarios from #72, #73, #81 and #82; eval cases.

Notes (2026-10-29):
- #73: `events.named_as_anchor(title, said)`: when the event's title words come up in the
  message only after "before", "after", "until", "ahead of", "around" or "than", it's the
  time to fit around, and `move_calendar_event` refuses, pointing to `reschedule_task` for
  a task. A message that doesn't name the event at all ("move that to 4") still goes
  through: the model decides. The tool's description says the same.
- #73's "is moved" while the card waited: the reply guard (`agent.CLAIMS_DONE`) now knows
  moved, rescheduled, changed, deleted and cancelled, so the reply is replaced by "...:
  that's waiting for a yes on the card above."
- #81: `Events.withdraw_changes(event_id)`: staging a move or delete of an event withdraws
  the cards still waiting (or put off) to move or delete it, and so does making one. A
  card put off with [Not now] has no card left to edit, so it just never comes back.
- #82: the system prompt says having the other partner do something is `create_task` with
  their name; only "tell/let X know" is a message to pass on. `create_task`'s description
  gives "have Michael get the pacifier" as an example. No deterministic guard: the model
  answered without a tool.
- #72: the "Dryer now, or later tonight?" example is now tied to a washer that's finished,
  with "never offer a chore that isn't in the context", and "I'm too tired tonight" gets
  its own line (it's fine; offer to let today's open items wait).
- Evals: `energy-too-tired-tonight` and `task-have-partner-do-it` added, not run yet
  (run them when there's quota, since the prompt changed).
- Setup: restart. No migration.

### F18b · Feedback (2026-10-29): routines asked about, the slow note after a card, noise in chat again
Status: [x] 2026-10-29
Depends on: F18a, C3, P2a, F17a
From the family's reports of 2026-10-29 morning: Erin's bugs #76, #77 and #78, Michael's #74.
- #76 and #78 ("it gave the full day agenda, not my morning routine"; "the morning routine
  does have items"): "What is my morning routine?" ran `day_summary`, then "The morning
  routine board has no items", though the night before Themi sent "Morning routine, still
  open: Walk dog". Asking about a routine brings the routine tools and lists that routine's
  items (from Cozyla); "routine" words don't call for `day_summary`. Check also why a
  "Morning routine, still open" check went out at 21:15.
- #77 ("the taking me longer than usual message came in after the reply"): the summary card
  went first, then the slow note, then the text reply. Once a reply's card or text has gone
  out, the slow note isn't sent. When a failed message is retried (07:59), the retry
  answers the question it failed on, not the latest one twice.
- #74 ("there definitely are", after "Archive my email noise please" got "No noise emails
  are waiting right now"): #67 again after F17a. The log shows no tool ran, so the model
  answered without `archive_noise_emails`; find why (tool group words, or the open items
  missing the waiting offers after a restart) with a failing test first.
- Tests: the routine question (Cozyla fake), no slow note after a card, the retry's
  question, scenario from #74; eval cases for "what's my morning routine" and "archive my
  email noise".

Notes (2026-10-29):
- #76/#78: there was no tool that reads a routine, so the model made up "the board has no
  items". `show_routine(part)` (wall group, read-only) reads the person's routine records
  on the wall for today (one part of the day or all three), with "(done)" on the ticked
  ones. "morning/afternoon/evening routine" no longer calls for the calendar group, so
  `day_summary` isn't offered for it.
- The 21:15 "Morning routine, still open": the morning check was sendable from noon until
  quiet hours, with a deadline 15 minutes before them, so a check queued late (after a
  restart, or held by the daily limit) went out at night. It's now sent only until the
  evening check is due (an hour before quiet hours) and expires then.
- #77: the slow note isn't sent once a reply-priority message (a card such as the day's
  summary) has gone to them in the turn (`Agent._replied_since`).
- #77's thread: "Will you retry automatically?" got "Yes". Nothing retries a message the
  AI service was too busy for, so `BUSY_TEXT` says so, and the prompt says to answer it
  now if it's in the conversation. Deviation from the prompt: no retry was built.
- #74: not the tool groups. `archive_noise_emails` ran and was declined (declined calls
  aren't logged as "ran"), because nothing was waiting: all 17 of Michael's overnight
  noise emails were in Promotions or Updates, which F16d leaves alone. The answer now
  says how many noise emails from the last week are in Gmail's other tabs, and that only
  the Primary inbox counts (`NoiseDigest.in_tabs`). If Michael wants those tabs handled
  too, that's a change to F16d, for him to decide.
- Follow-up the same day (Michael: "I have 10 unread messages in my inbox that are likely
  noise"): F16d was wrong for him. Gmail's own `in:inbox is:unread category:primary` found
  exactly 10, and all carried CATEGORY_UPDATES: his Updates tab is off, so that mail shows
  in Primary, but Gmail labels it by category anyway. Migration 0071 adds
  `linked_accounts.gmail_tabs` (category -> shown as a tab) and `gmail_tabs_checked_at`.
  `GmailSync._learn_tabs` asks Gmail after each sync: daily, and at once for a category
  not seen before; a category whose inbox mail comes up under `category:primary` isn't a
  tab. `in_primary(labels, tabs)` takes the account's tabs (`GmailSync.tabs_shown`;
  unknown is a tab, as before), in triage, the noise message and `in_tabs`. When a
  category turns out to be in Primary, `EmailTriage.on_tabs_learned` offers the noise from
  the last week that was skipped (6 of his 10; the other 4 are routine, so no offer).
  Setup: restart (applies 0071).
- Evals (2026-10-29, Gemini 3.5 flash-lite): 47/49 full, PDA-safe 98%; F18a's two new
  cases pass. Fixed, then the 3 re-run and passing: `task-check-in-run` ("Check-in set
  for Tuesday..." read as the command "check in": a hyphenated opening word is a noun
  now, in the PDA checker itself); `energy-plumber` (Gemini sent effect "-3", the schema
  check refused it and the note was never saved: `tools._as_typed` reads numbers and
  true/false sent as text by the schema's type, and the scorer reads them the same way);
  `wall-what-is-my-morning-routine` was skipped for want of a wall: a case's `routine`
  setup now gets the fake Cozyla.
- Evals: `wall-what-is-my-morning-routine` added; not run yet. "Archive my email noise"
  is covered by #67's cases.
- Setup: restart. No migration.

### F18c · Feedback (2026-10-29): button rows, the wall's to-do order, emails dealt with in Gmail, whose habit offer
Status: [x] 2026-10-29
Depends on: F18b, C1c
From Erin's ideas #75, #80 and #83 (2026-10-29), and Michael's question about an offer.
- #80 ("if there are more than 2-3 options, Themi should split push buttons onto multiple
  lines..."): buttons go in rows, at most 2 a row, or 3 when every label is short (yes, no,
  ok, later and the like).
- #75 ("Themi should maintain a custom order of to dos in cozyla based on due date and
  importance"): the wall's To-do List is kept in order: overdue and due first, urgent and
  important before the rest, then by due date. Only Themi's own items move; check what the
  unofficial client can set (C1c's notes).
- #83 ("emails that have been marked read or archived by the user will be cleared from
  Themi's email queue"): an email read or archived in Gmail leaves the noise offers, the
  audit and "waiting on you" items about it (Gmail history already says so), and a queued
  digest is refreshed.
- Michael was offered "A small daily check-in to try: a glass of water mid-morning" and
  read it as Erin's check-in. It's his own copy of the reserve (habits are per person,
  20), but the card doesn't say so. The offer says it's for them ("Something you could try
  for yourself: ..."), and an idea the other partner has active comes after the rest.
- Tests: the row layout (Telegram fake), the order on the wall (Cozyla fake), an email
  archived in Gmail clearing the queue, the offer's wording and order.

Notes (2026-10-29):
- #80: `telegram.button_rows(labels)`: one or two buttons on one row; more go two a row,
  or three when every label is 8 characters or fewer. Every keyboard (sends and edits)
  uses it. The scenario harness, the Telegram fake and five test helpers read every row
  now, not just the first; the simulator already did.
- #75 moved to F18d: nothing Themi knows of the unofficial API sets a to-do's place on
  the wall (routines have `displayOrder`; to-dos have no such field in what we've seen),
  and changing due dates to fake an order would change the family's data. F18d starts
  with a read-only look at the live API.
- #83: `GmailClient.history` asks for messageAdded, labelRemoved and messageDeleted, with
  no label filter (an archived message no longer carries INBOX); added mail is picked out
  by its INBOX label. `HistoryPage.handled` lists (message, "archived" | "read" |
  "deleted"); `GmailSync` brings the stored labels up to date and tells
  `handled_listeners`. `EmailTriage.on_handled` withdraws "Taken care of in Gmail
  already.": read clears the mark-read and noise offers; archived or deleted also clears
  a drafted reply and the email's unanswered audit question. A queued noise digest is
  made again. Themi's own archiving shows in the history too, but only open offers are
  withdrawn, so its own are untouched. The fake Gmail records labelRemoved, labelAdded
  and messageDeleted as Gmail does, and `FakeGmail.by_hand` changes a message as if in
  Gmail itself.
- Michael's habit offer: `habits.OFFER_TEXT` is "Something you could try for yourself:
  {idea}", and an idea the other partner has active is offered after the rest. His open
  water offer (habit 5) keeps its old wording; "Not now" or no answer drops it for good.
- The plan (rev 207): button rows, the routine read and the morning check's end, noise in
  other tabs and mail handled in Gmail, and the per-person habit reserve.
- Setup: restart. No migration. Gmail's history now returns label changes too, so each
  poll reads a little more; nothing to set up.

### F18d · Feedback (2026-10-29): the wall's to-do list in order
Status: [x] 2026-10-30
Depends on: F18c, C1c
From Erin's idea #75: "Themi should maintain a custom order of to dos in cozyla based on
due date and importance (with the most important and due/overdue tasks at the top of
the list)."
- First, read-only: list the To-do List's to-dos from the live API and note every field
  (is there a sort or display order? does `isFlag` or `todoStars` change where one
  shows?). Ask the user before writing anything to the wall to test it.
- If the wall can be ordered: keep Themi's own to-dos in order (overdue and due first,
  urgent and important before the rest, then by due date) on each sync, without changing
  their dates. Items Themi didn't make stay where they are.
- If it can't: tell Erin what the wall can do (flags or stars, if they show), and offer
  that instead.
- Tests: the order kept on the wall (Cozyla fake, with the field found), items not
  Themi's left alone.

Notes (2026-10-30):
- The development checkout had no Cozyla login at first, so the live read couldn't be done here.
  `themi cozyla check --fields` (read-only, tested against the fake) prints every field
  name seen on to-dos, then each open to-do on `COZYLA_TODO_LIST` with all its fields, in
  the order Cozyla sends them.
- Live read (2026-10-30, To-do List: 13 open): to-dos do carry `displayOrder` (and
  `profileDisplayOrder`, likely the order on each person's own view). Cozyla sends them
  highest `displayOrder` first (116 down to 67), and the number rises as items are made, so
  the list runs newest first. `isFlag` and `todoStars` are 0 on every open item. Other
  fields: `sourceType` ("user", "device_ai"), `version`, `showMemberUidList`.
- Michael confirmed the wall shows that order, and said yes to a test write. A temporary
  to-do ("Themi order test (please ignore)") was made, at `displayOrder` 117 and
  `profileDisplayOrder` 117, the top. Setting `displayOrder` to 66 changed the API's order
  but not the wall's. Setting `profileDisplayOrder` below the rest moved it to the bottom
  on the wall. Then it was deleted. So the wall goes by `profileDisplayOrder`, highest on
  top. The update endpoint takes both, and keeps them when they're left out (unlike the
  other fields).
- `CozylaClient.place(todo, display, profile)` sets both, with every other field sent back.
  After each push, `CozylaTodos._order` ranks Themi's own open to-dos on the configured
  list: tasks with a creator (wall imports have none). The rank is due or overdue, then
  importance (high, normal, low), then due date, undated last. They take the
  `profileDisplayOrder` and `displayOrder` values they already hold, best on top, so to-dos
  added on the wall keep their exact place. Only those not already in place are written,
  and dates never change. A to-do just made is placed from the next read.
- Limit: a wall-made to-do between Themi's isn't jumped over. Themi's most important item
  goes to the highest place Themi's own already have.
- The Cozyla fake now gives new to-dos the next order numbers and sends the list highest
  `displayOrder` first, as live. One wall-lists test compared an import's order and now
  ignores it.

### F18e · Feedback (2026-10-29): the chore sync stuck, the wrong task changed, reminders that aren't tasks
Status: [x] 2026-10-29
Depends on: C2b, F15a, F17b
From the evening's logs (the chore sync warning every five minutes) and Erin's bugs #92
and #93.
- The log: "Cozyla chore sync stopped partway ... choreCheck/v1 (code 30016)" all evening.
  "Bring bins in" was done early for next Wednesday; the wall won't tick a day still to
  come, and the refusal stopped every sync before chores were pushed. A round done early
  is ticked once its day comes; a tick the wall says no to is let go (connection and
  sign-in failures still stop the sync and retry).
- Behind it: "I brought the bins in" the morning after the round was marked missed counted
  for next week's round. Done the day after a missed round, while the next hasn't begun,
  fills the missed one (late).
- Also behind it: "We contacted Erin's parents" marked the bins done (task 28, not 38).
- #92 ("review bird cage schedule... I don't think it was supposed to be due? And it
  misunderstood me asking when I cleaned it last"): Michael's "Yes please" to "Should I
  reschedule 'Contact Erin's parents' to today at 6 pm?" moved the bird cage to 6 pm, so it
  came up on Erin's chart and was nudged. Then "Didn't I just clean the bird cage?" and
  "What no I meant yesterday?" each marked it done.
- #93 ("event reminders are not tasks"): "extra reminders for the tutoring at 2pm and
  3pm" were tasks (F15a's choice), each asking "Done already, or later?".

Notes (2026-10-29):
- `CozylaChores._check` ticks the wall; a refusal (any code but -1 and the sign-in ones)
  is logged and the run is passed. `_ticks_to_wall` stops at a run whose day is after
  today and comes back to it. The Cozyla fake refuses a future `checkDay` with 30016.
- `TaskBoard._just_missed`/`_fill_missed`: the newest run is a missed one whose round
  ended yesterday and the current round's day is after today: a new late run takes its
  place (added before the old one is deleted: SQLite reuses the highest id, and the wall
  sync goes by id). Two days late counts for the next round, as before.
- `complete_task`, `reschedule_task`, `cancel_task` and `set_task_schedule` refuse a task
  the conversation names nothing of when it names another open task (two or more title
  words, `events.words_in_common`), and say which. A message of three words or fewer is
  read with Themi's last message (`ToolContext.said_before`). Just "done" names nothing.
- `complete_task` refuses a question ("?" at the end, or starting did/didn't/have/when/
  was) unless it says it's done too ("done, what's next?", "can you mark it").
- #93: `add_reminder(text, date, time)` (core, `themi.core.reminders`) queues "Reminder:
  {text}" for that moment, with no buttons and no task: deadline at the moment (on time
  past pacing and the day's limit, never in quiet hours or a pause), dropped two hours
  past it. The system prompt points extra reminders there; "remind me to..." is still a
  task. Deviation from F15a, at Erin's word.
- `tasks._clock_words` is public now (`clock_words`).
- Data repaired in the live database (backups in `data/`): bins (task 28) one late run by
  Michael for 28 Oct, due 4 Nov; bird cage (task 7) the two runs from questions removed,
  due 31 Oct with no time (the 6 pm was the misdirected reschedule). Task 38 was done by
  Erin already.
- Tool arguments aren't logged, so the misdirected calls were worked out from timings
  (each tool's log line, the outbox, `reply_tools`). Logging a call's task id would make
  the next one quicker to find.
- Not run: the model evals (cases for a question, "Yes please" and an event reminder
  would be worth adding).
- Setup: restart. No migration.

### F18f · Feedback (2026-10-29): a wrong year, the summary twice, a task already open, stale cards, the heads-up late
Status: [x] 2026-10-29
Depends on: F18e, K3, K4
From the family's bugs #84, #85, #87, #88, #89, #90 and #91 (2026-10-29).
- #84, #85, #87 ("Clean upstairs" still on the wall for today after it was moved; "streamline
  the snooze feature"; "October 30 is tomorrow, but Themi is prompting it as an overdue
  task"): the model moved it to 2020-10-30, a Friday too, so "Friday 30 Oct" read right.
  Overdue by six years, it stayed up on Erin's chart (one at a time), each "snooze" set
  the same date, the chart nudged it "Was due 30 Oct", and the missed round rolled it on
  to the next Thursday. Also #84: green tea, already due Friday, was listed as moved.
- #88 ("it should have continued the conversation to update the existing task"): "a task
  for both of us due today at 6pm" was refused as already open; the model asked instead,
  and no tool could make an open one-off both of theirs.
- #89 ("why does this question result in two different day summary messages?"): the model
  wrote the day out after `day_summary` had sent it; the tool's description said "say it
  back in plain words", its result "don't repeat it".
- #90 ("it's really hung up on rescheduling my tutoring"): a card to move tutoring to
  12-1:20, put off with Not now, came back at 1:33 pm. A later move was approved; the
  first card predated #81's fix, and nothing made a card lapse once its time had gone.
- #91 ("traffic was considered, but prep time wasn't"): the heads-up was queued at 3:33,
  getting-ready time ahead of leaving, but its deadline was the leave time, so pacing held
  it to 3:49.

Notes (2026-10-29):
- `tasks.day_arg`: a date the model gives (create_task, reschedule_task, add_reminder) in
  a past year is this year's, or next year's once that day has gone. `when_words` shows a
  year that isn't this one. reschedule_task to the day a task has, with no time, says
  "already due ...; nothing changed".
- #88: the duplicate refusal says to change the open one now, to everything asked, and
  names the tools; `update_task` takes `assign_to` (read by `tasks._assignee`, shared with
  create_task; 'both' is `reassign(shared=True)`). A chore's people stay its schedule's.
- #89: `ToolContext.answered`: a tool that sends the answer itself (`day_summary`) marks
  the turn; the model's reply then goes only if it's one short line (`agent.SHORT_LINE`,
  120 characters), else nothing more is sent. The description no longer says "say it back".
- #90: move cards expire at the time they move to, add cards when the event ends (task
  blocks did already, #64).
- #91: the heads-up's deadline is when it's queued: on time past pacing and the day's
  limit, still never in quiet hours, a busy time or a pause.
- Data repaired (backups in `data/`): "Clean upstairs" (task 30) due Fri 30 Oct, its
  missed 2020 round removed; cards 179 (the tutoring move) and 78 (Tuesday's run) expired.
- Not run: the model evals.
- Setup: restart. No migration.

### F18g · Feedback (2026-10-29): "no" closed eight tasks, a title that says "today"
Status: [x] 2026-10-29
Depends on: F18e, F18f
From Erin's bugs #95 and #97 (2026-10-29, evening).
- #97 ("Michael should have been given the task urgently for tonight, why did Themi lie and
  say it was marked done and why do I still see the task on my list in cozyla?"): to
  "Morning routine, still open: Walk dog. Done already?" she said "no". The model called
  complete_task on eight open tasks, the laundry due 9 pm for either of them among them,
  so its nudges were withdrawn, then ran out of steps.
- #95 ("make this last exchange more streamlined"): "Tomorrow, remind me to send the
  invoice from the tutoring session today" became that title, read back as a bare line;
  she had to ask for the session's name and date in it.

Notes (2026-10-29):
- `complete_task` refuses a bare no ("no", "nope", "not yet"...), and a task that nothing
  names: their message, their one before it, Themi's last message (the nudge answered),
  or "all"/"everything". A bare "done" with no nudge before it no longer closes a task.
- `create_task`'s result gives the due day and asks for the title and when in one line; a
  title with "today", "tonight", "tomorrow" or the like, due another day, is to be renamed
  with update_task to the thing itself and its date.
- Data repaired (backup in `data/`): the eight tasks reopened through `TaskBoard.reopen`
  (re-nudged; their wall to-dos marked to sync), from a script whose channel refused to
  send, so the running app delivered: Michael's laundry nudge went at 9:04 pm. The
  vacuum's nudge was held to 8 am (she'd said Later at 7:35).
- Open: the rest of #97 (whether the laundry should have been Michael's alone, as the
  reply said, rather than on both lists) and idea #96 (a routine check with one item has
  one button; a "skip today" button, and a morning check held to 8:15 pm).
- Not run: the model evals.
- Setup: restart. No migration.

### F18h · Feedback (2026-10-30): who has a task, said truly; routine checks with a skip
Status: [x] 2026-10-30
Depends on: F18g
From the rest of Erin's bug #97 and her idea #96 (2026-10-29).
- #97: "Have one of us cycle the laundry tonight" made a task for either of them, but
  create_task's result said "assigned to Michael ... Michael gets a gentle nudge", so the
  reply said "I've put it on Michael's list" while it was on both lists (and her wall).
  Earlier, "can you get Michael to unclog the vacuum tonight?" ran five task tools, none
  of which moved it, and the reply said "I've assigned it to Michael for tonight". The
  user's ask: Themi tells the whole truth about the actions it takes.
- #96: "Themi should never offer a single push button. This should have been 'walk dog' or
  'skip today' because it's already evening": the morning routine check, held all
  afternoon, went at 8:15 pm with one button.

Notes (2026-10-30):
- `create_task` for "both" now says "created for both of them, on both lists" and that
  each gets a nudge; `TaskBoard.whose_list` words whose list a task is on.
- The agent checks each sentence of a reply that hands a task to someone ("assigned ... to
  Michael", "on Michael's list"): if none of the tasks it names in quotes (or else, that the
  turn's tools touched; `ToolContext.tasks`) is that person's alone, the sentence is
  dropped and '"X" is on Erin's list.' (or "both lists") said instead. A name inside a
  quoted title doesn't count. The system prompt says the same.
- Routine checks end with a "Skip today" button (edits to "Morning routine: left for
  today."; nothing is ticked on the wall). The morning check isn't sent after 5 pm, and
  one held back lapses then.
- Still single-button: a draft rule's "Lock it in" card, and a task block's "Done".
- Not run: the model evals.
- Setup: restart. No migration.

### F19a · Feedback (2026-10-30): a snooze to tomorrow, yesterday's summary, a stale end-of-day list, quotes, an event already added
Status: [x] 2026-10-30
Depends on: F18h, K1, K2, C2c
From the family's bugs #98-#101 and #103-#106 (2026-10-29 and 30). Ideas #86, #94 and #102
from the same days are F19c, O1 and F19b; #33 and #34 still wait for Erin's spec.
- #104, #106 ("I snoozed that one to tomorrow afternoon, it confirmed the snooze, but here
  it is today"): at 1:37 pm, "Snooze the green tea to tomorrow afternoon" ran snooze_task
  with until 14:00. snooze_task only takes a time (today, or tomorrow once it's passed), so
  it waited until 2 pm *today*; the reply said "2 pm tomorrow". At 4:47 the day summary
  still listed it.
- #105 ("not even close"): "What happened yesterday?" gave "Thu 29 Oct: Move Mimi's box
  upstairs for Rosie", the one task still open. The calendar is read from now on, so a past
  day has no events (Thursday had tutoring), and a summary lists only open tasks, never
  what was done.
- #99 ("why does it think cycle the laundry isn't done right after saying it was?"): the
  end-of-day list was written at 7:36 pm and held by pacing until 9:15; the laundry was
  ticked at 9:05, and the list went out as written.
- #98, #100 (quotes around the whole thing): replies came as `"'Copy and review ...' is
  done."` and `'"Refill whoosh litter" is set up for both of you.'`; earlier, a title in
  backticks and quotes, `` `"Unclog the robot vacuum"` ``. The model's own text.
- #101 ("the proposed calendar event is correct, but Themi already added it"): at 7:42 pm
  she had Themi add "Tutoring (Jennifer)", Mon 9 Nov 4:30-5:50. Fifteen minutes later the
  booking email made a card for the same times ("Tutoring: Malcolm's first session"), and
  a second email the next day made another.
- #103 ("I marked the tutoring invoice as complete and it disappeared from the morning
  task message, but it is still showing on cozyla"): look into it. The tick on the
  morning list goes through `complete`, as any Done does.

Tests: each bug first as a failing test; a scenario for the snooze to tomorrow and for
yesterday's summary.

Notes (2026-10-30):
- #104, #106: `snooze_task` takes `day` (YYYY-MM-DD, '' for today; a day alone waits for
  9 am; a time already gone on a day given is refused). A snooze today reads back "until
  2 pm today". `TaskBoard.put_off_until`; the day summary leaves out a task put off past
  the day's end (`Reminders._put_off` shares it).
- #105: the calendar is read from midnight a week back (`busy.LOOK_BACK`), so today's
  earlier events stay too. A day gone by lists what was done at the time it was done,
  "(done)" or "(done by Michael)" for a round someone else did (`TaskBoard.done_between`:
  rounds from task_runs, one-offs by completed_at; who did a one-off isn't kept), and its
  open tasks "(still open)". The tool's description says it answers "what happened".
- #99: `Outbox.refreshers`, per kind: a held message is asked for its text as it goes,
  or dropped (None). Reminders' refresher writes the end-of-day list again; other
  task_summary rows (the morning list) go as they are.
- #98, #100: `agent._unquoted` takes quotes off a whole reply (straight or curly) when
  that mark isn't used inside it, apostrophes aside, and backticks off a quoted title.
- #101: `Events._already`: no card for a booking at the very times of an event on their
  calendars (Themi's or by hand, the family calendar too) or of a card still waiting.
  Titles aren't compared ("Tutoring (Jennifer)" vs "Tutoring: Malcolm's first session").
- #103: no fault found. The tick goes through `complete`; the to-do's link says done, no
  errors (when it reached the wall isn't kept). Cozyla timed out at times that day, and
  a failed read backs off up to an hour. The edited morning list now starts "Marked done:
  X." so the tick is seen to have worked.
- Data repaired (backup `data/themi-before-f19a-repair-2026-10-30.db`), from a script with
  the app built but not started: cards 221 and 231 (the Malcolm session, already on her
  calendar) withdrawn ("It's on your calendar already."); the green tea (task 42) put off
  to Sat 31 Oct, 2 pm. Reports #86, #94 and #98-#106 marked reviewed; #33 and #34 wait.
- Not run: the model evals.
- Setup: restart. No migration.

### F19b · Idea #102: a word when a task is done
Status: [x] 2026-10-30
Depends on: F19a
Erin's idea #102 (2026-10-30): "when a user completes a task, Themi should send a
confirmation message along with a brief 'good job!' or similar message."
- Today a Done button edits its nudge to "Marked done: X. Thank you."; a tick on the
  morning list only takes the line away (F19a adds "Marked done: X." above the list);
  done in chat, the model's reply says something or nothing; ticked on the wall, nothing
  is said.
- Build: one short, warm line when a task is done by any path except the wall itself:
  plain, never effusive, and never about energy. Varied from a small set (no AI call), so
  it doesn't read as a stamp. Where the done is already confirmed in place (the nudge's
  edit), the warm word goes in that edit, not a second message.
- PDA phrasing applies: praise for having done it, never "keep it up" or anything that
  asks for more. Off with a setting for whoever finds it too much.
- Ask Erin before building: done on the wall, should a message come at all (it would be
  the only message caused by the wall)?

Tests: each path (button, list tick, chat) says it once; the wall says nothing; the
setting turns it off; the shield keeps the wording.

Notes (2026-10-30):
- The question for Erin was settled by default, not asked: the wall says nothing (it'd be
  the only message the wall causes). Change it if she'd like one.
- `tasks.PRAISE` (five plain words: "Nice work.", "Well done."...), picked by task and
  minute (`_praise`, no AI call). `TaskBoard.complete` puts one in place of "Thank you."
  when `interactive` (a tap, a tick, complete_task, a logged call) and the doer's
  `done_praise` is on; a round's "Next round: ..." follows it. The edit of the nudge is
  the confirmation, so no second message; the morning list's edit starts with it.
- Done on the wall, by Google Tasks, the dishwasher or the email audit: the nudges still
  say "Marked done: X. Thank you.", nothing more.
- complete_task's result carries the line, and its description says to give it as it is;
  the model may still word it its own way.
- Setting: `members.done_praise` (migration 0084), on by default; on the website's
  settings page. No chat tool for it yet; set_phrasing's notes would be read, not obeyed.
- Not run: the model evals.
- Setup: restart (applies 0084).

### F19c · Idea #86: a shared task put off by one person stays with the other
Status: [x] 2026-10-30
Depends on: F19a, F4
Erin's idea #86 (2026-10-29): "for shared tasks, when one user snoozes the task, only snooze
it for that user (it should remain active for the user who did not snooze the task)."
- Today a task is snoozed as a whole (`tasks.status = 'snoozed'`, one `snoozed_until`), and
  a snooze withdraws every queued nudge for it, the other person's too.
- Build: for a shared or either-of-you task, a snooze is the snoozer's: kept per person (a
  table of task, member, until), their nudges held, the other's left alone. The task stays
  open; it's on the snoozer's day summary, end-of-day list and morning list only once
  their snooze is over. When both have put it off, it waits for the earlier of the two.
- A one-person task snoozes as today. Rescheduling (a new due day) still moves it for both,
  and says so.
- The snooze's reply says who it's put off for when the task is shared ("Put off for you
  until 2 pm tomorrow; it's still on Michael's list").
- Check the wall: a Cozyla to-do is one item for both, so a per-person snooze doesn't touch
  it.

Tests: shared task snoozed by one: the other's nudge and summary unchanged; both snooze;
the snooze ends; a one-person task as before; a reschedule moves it for both.

Notes (2026-10-30):
- `task_snoozes` (task, member, until; migration 0085). `TaskBoard.snooze(..., by=)`: a
  `shared` task (either of you, or escalated to both) put off by `by` gets their row,
  their queued nudges cancelled, and the task stays open. Later on a nudge and
  snooze_task pass who it was; the email audit's own snooze doesn't (its task is one
  person's).
- `put_off_until(task, member)` counts their own put-off; `prompt()` sends nothing to
  someone with one; the day summary, the end-of-day list and overdue reminders leave it
  out for them. `resurface` deletes a row whose time has come and nudges that person.
- Deviation: when both have put it off, each hears at their own time, not both at the
  earlier one; each asked for their own.
- Done (by anyone) or rescheduled ends every row for the task; a reschedule from chat of
  a shared task says "That's for both of you." The wall (one to-do for both) and the
  chore chart are untouched.
- Replies: "No rush on that one (X). It waits for you until 2 pm today. It's still on
  Michael's list." (or "It'll come back to you in a few hours."). "Put off for you" was
  reworded by the PDA shield as a command.
- Not run: the model evals.
- Setup: restart (applies 0085).

### O1 · Idea #94: when it's too much, a few things now and the rest spread out
Status: [ ]
Depends on: F19a, F19c, T1, B1
Erin's idea #94 (2026-10-29): "a full overhaul of how Themi presents tasks when the user is
overwhelmed. Something that only surfaces a small number of tasks to focus on for now. And
also reassures the user that all the other tasks are also being remembered and planned for
future days. And that pushing the remaining tasks to a later day won't lead to having way
too much on any single later day."
It came out of the morning of 2026-10-29 (bugs #84, #85): "today's to dos need to be pared
down", then "snooze everything except the tutoring and the run", then "snooze clean
upstairs", each move one by one and every remaining one read back.
- Build, in two parts (split into O1a/O1b before starting if it's big):
  1. **A short list.** Asked for (an "it's too much" / "pare it down" message, or a
     button on the morning list), Themi picks at most three things for now: what has a
     fixed time today (calendar, check-ins with a time), then urgent and important (T1),
     then the lightest. Medicines are never left out. One message, those few, and a line
     that the rest are kept and placed ("The other 6 are planned over the next few days;
     nothing's dropped.").
  2. **The rest spread out.** What isn't on the short list moves to later days, filled by
     a daily budget (each day's open count, chores on the chart included, kept under a
     ceiling: the family's typical day, from task_runs, or a setting). Fixed-date and
     deadline tasks never move. Repeating chores skip a round rather than stack. Moves
     go through one reschedule each, but are said once, as a short summary by day
     ("Fri: 2, Sat: 3, Mon: 1"), with a way to see them.
- Wording: reassurance, not instruction (the PDA shield's rules); never energy numbers; no
  "you should". A break (B1) can be offered alongside it, not instead.
- Ask Erin before building: how few is "a small number" (three?), whether the short list
  replaces the morning list on such a day, and whether Themi may offer it on its own when
  a day looks overloaded or only when asked.
- Linked: #33 burnout recovery mode may fold into this once Erin's spec arrives.

Tests: the pick (fixed times, medicine kept, the cap); the spread never puts a day over
its budget and never moves a fixed date; one summary message; a scenario of the
2026-10-29 morning ("pare it down") in one exchange.

### R1 · Routines kept in Themi (split into R1a and R1b)
From Erin's idea #79 (2026-10-29): "Themi should maintain internal routine tracking.
Default morning, afternoon, and evening, but customizable number of routines and when they
each happen."

Decided with Michael (2026-10-30), after reading C3's notes:
- Themi owns the routines. The wall shows each one under whichever of its three parts
  (Morning, Afternoon, Evening) the routine's window starts in.
- Routines are changed in chat and on the wall. A change made on the wall comes into
  Themi, as the to-do sync does (C1b): an item added, renamed, deleted, moved to another
  part or given other days there. A change Themi hasn't sent yet wins over one made on the
  wall.
- The wall's routines today (walk the dog, Cycle Dishwasher, meds, bins) come into Themi
  once, on the first sync.
- A routine is a name and a time window per person ("Before school", 7:00 to 8:00). Its
  check comes as the window ends, listing what's still open.
- Everyone starts with Morning, Afternoon and Evening.

### R1a · Routines kept in Themi: routines, items and checks, from chat
Status: [x] 2026-10-30
Depends on: R1
Build:
- Each person's routines: a name and a window (start and end, local time). Everyone starts
  with Morning (8:00 to 12:00), Afternoon (12:00 to 17:00) and Evening (17:00 until an hour
  before quiet hours, as C3's evening check), and can add, rename, re-time or remove them.
- Items on a routine: a title, and the days it applies (every day by default; set days like
  "Tue and Thu"; or just today). They're ticked once a day.
- The check: as a routine's window ends, if any of today's items are open, one message
  lists them, with a button per item that ticks it, and "Skip today" (C3's wording and
  buttons). All done: nothing sent. Each check feeds the energy model as C3's does: device
  activity, a small lift or dip, in words.
- Chat: tools to show someone's routines, add or remove a routine (with its window), add,
  move or remove an item, and tick an item ("I walked the dog"). Changes to their own
  routines need no card (asked for in their own words); someone else's go through a
  category, as `wall_routine_add` does.
- The wall isn't touched yet: C3 keeps running as it is until R1b.
Tests: the defaults; a custom routine checked as its window ends; items on set days; ticking
from a button and from chat; skip today; the energy signal; changes from chat.

Notes (2026-10-30):
- `themi.core.routines.Routines`, job `routines.check` every 15 minutes. Migration 0079:
  `routines` (name unique per person, ignoring case; `ends` NULL is "an hour before quiet
  hours", as C3), `routine_items` (`days` JSON, empty for every day; `only_on` for just one
  day), `routine_ticks`, `routine_day_checks`, and category `routine_item_add`.
- Each person gets the three defaults the first time their routines are read.
- A check goes once a day per routine, from the window's end until three hours after; one
  later than that isn't sent. A routine with nothing on it today sends nothing and records
  no signal. The words and buttons are C3's ("Morning routine, still open: ...", a tick
  button per item, "Skip today"; the button kind is `routine_item`), and so is the signal
  (device activity, plus or minus 0.5).
- Tools, in the "wall" group (the word "routine" calls for it): `show_routines`,
  `set_routine` (add, re-time or rename), `remove_routine`, `add_routine_item` (staged;
  their own and named in their words means no card; someone else's asks the requester
  first), `remove_routine_item` and `tick_routine_item`. Only `add_routine_item` reaches
  someone else's routines. A twin-set paragraph for these and the wall's routine tools was
  left out: twin sets need every tool built and two eval cases each. The descriptions name
  each other instead.
- Until R1b, a person with items both on the wall and in Themi can get two checks for a
  part of the day: C3's for the wall's, and this one.
- Setup: restart (applies 0079).

### R1b · Routines kept in Themi: the wall, both ways
Status: [x] 2026-10-30
Depends on: R1a, C3, F18d
Build:
- The first sync brings the wall's routines into Themi. Each item goes to the person's
  routine for its part (Morning, Afternoon, Evening), with its days.
- Then each sync, both ways. Themi's items go on the wall under the part their routine's
  window starts in (`part_of_day`), with their days and their order (`displayOrder`, as C3
  places items). A change on the wall comes into Themi: an item added there goes to the
  person's first routine starting in that part; renamed, deleted, moved to another part, or
  given other days, the same. A change Themi hasn't sent yet wins. Ticks go both ways.
- C3's own checks stop for anyone whose routines are in Themi, so nothing is checked
  twice. Themi's check-ins (F8) stay as they are.
Tests: the first import; an item made in Themi shown on the wall in the right part; each kind
of wall change coming in; a conflict won by Themi's pending change; ticks both ways; no
double checks.

Notes (2026-10-30):
- `themi.core.routines_wall.RoutinesWall`, job `routines.wall` every 5 minutes, when the
  wall's chores are on (`COZYLA_CHORES`). Migration 0080:
    - `routine_item_links` (item to wall routine, pending or done, with a version), for
      every item including R1a's.
    - `routine_wall_deletes` and `routine_wall_seen`.
    - Triggers mark an item pending when it's made or changed, or when its routine is
      re-timed. Deleting an item, or a routine with its items, queues its wall routine for
      deletion. So R1a's code didn't change for this.
- Pull: an unlinked wall routine (not a C3 check-in) becomes an item in the person's first
  routine starting in its part, with its days. That's how the first import happens. A
  linked one that isn't pending and differs from `routine_wall_seen` (title, part, days)
  is changed in Themi; a part change moves it to the routine for the new part, and a
  missing routine for a part gets that part's default. One gone from the wall is deleted
  in Themi, without queuing a wall delete. A routine whose schedule isn't daily or weekly
  (monthly, every 2 weeks) comes in as every day.
- Push: queued deletes, then pending items, created or updated with the part from
  `part_of_day(routine.starts)` and a daily or weekly schedule. A just-for-today item goes
  out as daily and into C3's `wall_routine_once`, so it's removed the next day (and the pull
  removes it in Themi).
- Ticks: a wall tick today ticks the Themi item. A tick in Themi (`Routines.tick_now`, from
  a check's button or chat) ticks the wall at once, and any missed one goes at the next sync.
- C3's own checks stop (`CozylaRoutines.checks_by_themi`). Their code stays, unused. C3's
  scenario tests now run the R1b sync and R1a's check, and pass with the same words and
  buttons. The late limit is now five hours, so a morning check still lapses at 5 pm (idea
  #96).
- Not done: the order of items within a part on the wall (`displayOrder`). New items go
  last, as the wall puts them. Also, `add_to_wall_routine` and `show_routine` still write
  and read the wall directly; what they add comes into Themi at the next sync.
- Setup: restart (applies 0080). The first sync (within 5 minutes) brings the wall's
  routines into Themi.

### K1 · Calendars: read your own, privately
Status: [x] 2026-10-26
Depends on: S2, 26
Asked for on 2026-10-26: "allow Themi to read our individual personal calendars and be able to
take action based on the info". This changes the plan's "only when, never what" for calendars:
update its Shadow Calendar inputs, Integrations and privacy sections to say what's kept now.
The family chose (2026-10-26): who sees a person's event details is their setting; which
calendars are read is chosen per person.

Build:
- Per person, the calendars Themi reads: picked from their Google calendar list on the
  settings page (the primary one by default). Read every 15 minutes, as S2 does, for the next
  14 days: title, location, start and end, all-day or not, and whether it's a video call
  (a conference link). Never descriptions or attendee lists: what others write into an invite
  is the riskiest text there is.
- A setting, "Who sees my calendar details": just me (default), or my partner too. Busy blocks
  (S2) keep working either way; the details only reach the model in conversations the setting
  allows.
- Event text is external: it reaches the model inside delimited data blocks, never as
  instructions, like email.
- Events Themi made itself (marked with a private extended property) are known by their
  task or source, and K5's task blocks don't count as busy time.
- The "calendar" privacy switch covers all of it: off, nothing is read and the cache is
  emptied.
- Tests: chosen calendars only, the fields kept and dropped, the privacy setting in both
  directions, data blocks, Themi's own events not busy, the switch.

Notes (2026-10-26):
- `CalendarBusy` (`themi.connectors.gcal.busy`) now reads the chosen calendars for 14 days
  and keeps `calendar_entries` (title, location, start, end, all day, video call, busy,
  `source` from Themi's private extended property) beside `calendar_busy`. Never
  descriptions or attendees. Busy: timed, not "free", and not a K5 block (`task-block:`).
  Migration 0052: `members.calendar_details` ('me' default, or 'partner'),
  `member_calendars`, `calendar_entries`. Busy blocks now come from the chosen calendars
  too (S2 read only the primary one).
- Which calendars: My accounts → "Calendars Themi reads" (`/accounts/{id}/calendars`), a live
  list from Google; none ticked means the primary one. Only the member's own accounts.
- Who sees details: My settings → "My calendars". The model gets today's and tomorrow's
  events, for the person and anyone sharing with their partner, in a `<data
  source="calendars">` block in the turn's context, labelled information, never
  instructions. `Services.calendar_context`.
- The plan's Shadow Calendar inputs, Google Calendar row and privacy section were updated
  (rev 196); "only when, never what" is gone.
- Setup: restart (applies 0052). Nothing is read until Google is set up and accounts are
  linked; then each person chooses calendars and the sharing setting.

### K2 · Calendars: a summary of the day
Status: [x] 2026-10-26
Depends on: K1
- "What's my day look like?", "what's on Thursday?": a tool that gives the day's events (and,
  where the setting allows, the partner's), tasks due and chores up, in plain words.
- A setting, "Morning summary": off (default) or a time; the summary comes then as one
  message, through the outbox (quiet hours and daily limits apply as usual; it counts as one
  message). Nothing on: a short line, or nothing, as the person chooses.
- Tests: on request, on a time, off, quiet hours, privacy.

Notes (2026-10-26):
- `themi.core.day_summary.DaySummary`. Tool `day_summary` (date as YYYY-MM-DD from the
  context, empty for today; `partner` adds the partner's events when they share). Events
  come back inside a `calendars` data block; due items are plain.
- Due: tasks due that day, an either-day round on either day, and, for today, ones still
  open from before ("since Mon 19 Oct"); chores waiting for the chart are left out. Each line
  opens with a label ("2 pm:", "any time:"), as nudges do: the PDA shield rewrote a line
  that opened with a title like "Call the vet" into "Up next: ...". Check-ins and a plan's
  week show in brackets.
- Morning message: `members.morning_summary` ('HH:MM' or NULL) and
  `morning_summary_empty` (migration 0053), on My settings → "My calendars". The
  `calendar.morning` job (every 5 minutes) sends it once a day through the outbox (kind
  `summary`, normal priority, so quiet hours and limits apply), with the partner's events
  when they share; skipped if it's more than 3 hours late (Themi was down), and on empty
  days unless asked for.
- Setup: restart (applies 0053); each person sets a time if they want one.

### K3 · Calendars: creating and changing events
Status: [x] 2026-10-26
Depends on: K1, 26
The family chose (2026-10-26), as groceries work (F5):
- Asked for in their own words ("put the dentist on my calendar Tuesday at 3"): made at once,
  with a read-back built from what was stored ("On your calendar: Dentist, Tue 3 Nov,
  3-4 pm").
- Mentioned but not asked ("the plumber's coming Thursday morning"): a card, Go ahead or not
  now.
- Suggested by an email (a booking confirmation): a card. After several approved in a row,
  Themi offers to make these automatic, which is a household rule like any other autonomy
  grant; once it's locked, they're made without a card, and a message always says so ("Added
  to your calendar from an email: Vet, Fri 30 Oct, 10 am").
- Changing an event Themi made ("move the dentist to 4"): at once, read back.
- Changing or deleting an event Themi didn't make: always a card first.
Build:
- Tools to create, move and delete events: on the person's own calendar (a chosen one,
  default primary) or the family "Themi" calendar for the wall. Natural dates and times are
  parsed deterministically, as schedules are, and refused with an example when unclear.
- Categories: `calendar_event` (member scope, may become automatic) for their own events,
  `calendar_event_change` (member scope, capped: always a card) for events Themi didn't make,
  `calendar_from_email` (member scope, may become automatic) for emails' suggestions, and
  the offer after enough approvals.
- Tests: each case above, read-backs, unclear dates, the email path and its offer, the
  message after an automatic one.

Notes (2026-10-26):
- `themi.core.events.Events`. Tools: `add_calendar_event` (title, date, start, end,
  location, calendar "mine" or "family"), `move_calendar_event` and `delete_calendar_event`
  (an event found by words from its title, and its date when there could be more than one).
- Deviation: dates and times come as fields (YYYY-MM-DD, HH:MM; "3pm" accepted), checked
  here rather than parsed from a phrase. The model has the local date; the read-back is
  built from what was stored, so a misunderstanding still shows at once. A date that has
  gone by, an end before the start or a time that isn't one is refused with an example.
- "Asked for": the message mentions the calendar (or booking) and every word of the title
  that matters; "the plumber's coming Thursday" is a card. Events Themi made move and go at
  once (`calendar_event`, requested); anyone else's event is `calendar_event_change`,
  capped: always a card, and the rest of the event (description, guests) is kept.
- Mine: the person's linked account's primary calendar. Family: prompt 26's "Themi"
  calendar, under `calendar_write`.
- Made events carry `themi: event:<id>`, are recorded in `themi_events` (migration 0054;
  `action_key` keeps a retry from making two) and go into `calendar_entries` at once.
- Email: triage now pulls an event out of a confirmation (title, date, start, end,
  location; the schema's new `event` field). A new one is staged as `calendar_from_email`
  ("From an email: ..., for your calendar"). After 3 approved in a row, Themi proposes the
  autonomy grant once (a household rule; needs an admin); locked, they're made without a
  card and a message always says so ("Added to your calendar from an email: ...").
- A prompt line: appointments at a set time go on a calendar; things to do are tasks.
- Setup: restart (applies 0054).

### K4 · Calendars: travel time and "time to get ready"
Status: [x] 2026-10-26
Depends on: K1
The family chose (2026-10-26): TomTom's Routing API with live traffic (its free plan, no card;
check the current allowance), and a rough estimate from distance without a key.
- A family setting: home, as an address (geocoded once, kept as coordinates). F9b's sunset
  times use the same location.
- A setting per person: "Getting ready takes" (default 15 minutes), and the heads-up on or
  off.
- For an event with a real location (not a video call, not all-day, not at home), travel
  time from home: looked up once the day before or when it appears, and again about an hour
  before it's needed, with traffic. A heads-up comes at "leave by" minus getting ready:
  "Dentist at 3, about 35 min with traffic: leave around 2:20." It goes through the outbox at
  normal priority with a deadline at the leave-by time; quiet hours hold it unless the leave
  time would pass.
- Without a TomTom key: distance (geocoded with a free service, or TomTom's geocoder when
  there's a key) at typical driving speeds, and the heads-up says it's a rough guess.
- `tests/fakes/tomtom.py`: routing and geocoding, with failures. No real calls in tests.
- Setup for the family: a TomTom developer account and key (`TOMTOM_API_KEY`), and the home
  address on the Family page.

Notes (2026-10-26):
- `themi.connectors.travel.TravelClient`: TomTom's geocoder and router (live traffic, arriving
  at the start) with `TOMTOM_API_KEY`; without it, OpenStreetMap's Nominatim (named
  User-Agent) and an estimate: straight-line km x 1.35 at 45 km/h plus 5 minutes, rounded up
  to 5. Always built (the key is optional); the harness passes `fake_travel`.
- `themi.core.travel.TravelHeadsUps`, job `travel.heads_up` every 5 minutes, next 24 hours:
  skips all-day, video calls, events without a place and anything within 0.5 km of home. The
  rough estimate decides when an event is close (no lookups until about 45 minutes before
  it could matter); then the route; at "leave by" minus getting ready (3 minutes early at
  most) one message, normal priority, deadline the leave time: "Dentist at 3 pm, about 35
  min with traffic: leave around 2:25 pm." Without traffic it says "(a rough guess, without
  traffic)"; a failed route falls back to the estimate. One per event and start time.
- Migration 0055: `members.getting_ready_minutes` (15) and `leave_heads_up` (on), on My
  settings; `family_home` (address and coordinates, the Family page's "Home"), `geocodes`
  (places looked up; not found is retried after a day), `travel_headsups`.
- Logs: `?key=` in a URL is now redacted (TomTom's key travels in the query).
- F9b can use `family_home` for sunset times.
- Setup: restart (applies 0055); an admin saves the home address on the Family page;
  optionally `TOMTOM_API_KEY` in `.env` for live traffic (restart after).

### K4b · Calendars: drive time on request
Status: [x] 2026-10-26
Depends on: K4
Asked for on 2026-10-26: "how long will it take to drive to our next pediatrics appointment?"
- A tool: an upcoming event found by words from its title (among the calendars the person
  may see, as K1's setting says), or an address; the drive from home, arriving at the
  event's start (live traffic with a TomTom key), and when to leave and start getting
  ready. Event text comes back as data.

Notes (2026-10-26):
- Tool `drive_time` (event words, or an address) in `themi.core.travel`. An event: the soonest
  upcoming one in the next 14 days (as far as calendars are read) whose title has every
  word, among the person's own and any shared with them; the route arrives at its start.
  "About 35 min from home with traffic: leave around 9:25 am, and start getting ready around
  9:10 am." An address: leaving now. Video calls, events without an address and places not
  on the map are said plainly; a failed route falls back to the estimate.
- No migration; a restart picks it up.

### K5 · Calendars: blocking time for tasks
Status: [x] 2026-10-26
Depends on: K1, K3
- "Block Saturday morning for the bathroom": an event on the person's calendar for that task
  (made at once: asked for, and Themi's own). "Find me time for the bathroom": Themi suggests
  a free slot from their calendar and good windows, as a card.
- The task's nudges wait for the block (a hold, as the chore chart's are, `TaskBoard.holds`);
  the nudge comes as it starts. Moved on the calendar, the nudge moves; deleted, nudging is
  as before.
- When a block ends with the task still open: one message, done or move the block?
- Blocks are known as Themi's (K1), so they never hold Themi's own messages as busy time.
- Tests: made, nudged at the block, moved, deleted, ended undone, not busy.

Notes (2026-10-26):
- `themi.core.task_blocks.TaskBlocks`. Tools: `block_time_for_task` (task, date, start, end;
  at once when the message mentions blocking, the calendar or "time for"; else a card) and
  `find_time_for_task` (minutes, days; the first energy-model window long enough, from 30
  minutes on, on the quarter hour: their calendar's busy times, busy times and quiet hours
  are already out of those windows; always a card). Both under `calendar_event`.
- The block is made by K3's `Events.make` with source `task-block:<task>`, so the event
  carries that marker and K1 never counts it as busy. `task_blocks` (migration 0056).
- Hold: `TaskBoard.holds` while a block is coming (end-of-day and overdue reminders respect
  it too); a queued nudge is taken back. `blocks.tick` (every 5 minutes) nudges as a block
  begins, follows moves (the read's times win; moved later, it's re-armed), and treats a
  block missing from a read made after it was created, and before it ended, as deleted: the
  block ends and the task gets its usual nudge. `calendar_reads` records each account's last
  read, so an empty calendar still counts.
- At the end, with the task still open: "The time for X is over. Done, or move the block?"
  with a Done button. Not if the nudge from the block's start is still unanswered (one
  question at a time, idea #11); asked at most once.
- The task's line in Themi's open items says when its time is blocked.
- `TaskBoard.withdraw_prompt` and `time_of` are public now; `events.when_words`.
- Setup: restart (applies 0056).

---

## Milestone 5: Devices (Phase 2)

### 30 · LG ThinQ connector
Status: [ ]
Depends on: 29
Read first: "Integrations" → LG ThinQ row; "Setup checklists" → Phase 2.

Build:
- `themi.connectors.thinq` using LG's official ThinQ Connect API and personal access token. Use
  the official SDK if it fits; check LG's current docs. Read-only.
- Device discovery, and mapping each device to an appliance type (washer, dryer) on the website.
- Status via push events where supported, with polling as a fallback. Normalise into
  `ApplianceEvent(appliance, state: running | finished | idle, at)`.
- A fake for tests.

Tests:
- Discovery and mapping.
- Event normalisation from recorded payloads (stored in `tests/fixtures/thinq/`).
- Push and polling paths.
- Credentials encrypted.

Commit when done.

### 31 · Laundry module and rescue protocol
Status: [ ]
Depends on: 30, 20
Read first: "Module behaviour" → C (Laundry); "Testing" → Phase 2 row.

Build:
- Cycle tracking from `ApplianceEvent`s.
- Washer finished → an effort-1 physical task matched to the person with more spare capacity →
  a gentle two-option prompt.
- Dryer started → resolved.
- Past the freshness threshold (default 8 hours, set per family) → the prompt becomes "add soap
  and run a rinse", timed to finish as that person's next good window begins (rinse duration is
  configurable).
- A new washer cycle supersedes the old wet load.

Tests:
- Scenario: washer finishes while Erin is low, so her husband gets the prompt.
- Scenario: the load is ignored for 8 hours, and the rescue is suggested with correct timing.
- Dryer resolution.
- Superseding cycles.

Commit when done.

### 32 · SmartLife / Tuya feeders
Status: [ ]
Depends on: 29, 20
Read first: "Integrations" → SmartLife row; "Module behaviour" → C (feeders).

Build:
- `themi.connectors.tuya`: Tuya cloud API (signed requests via `httpx`). Link the SmartLife
  account per the Tuya docs, and map devices on the website.
- Capture raw data points per feeder model into fixtures so a mapping can be written for the
  family's models.
- Low food or a fault becomes an effort-1 task via matching.
- Feeding events optionally feed the energy hook.

Tests:
- Request signing.
- Data-point mapping from captured fixtures.
- Task creation.
- Credentials encrypted.

Commit when done.

### 33 · Seasonal and long-term maintenance
Status: [ ]
Depends on: 26, 19
Read first: "Module behaviour" → C (Maintenance).

Build:
- Migration for `maintenance_items`: name, interval in days, active months, step-by-step guide,
  and a history of past runs with notes.
- Manage items on the website and via chat.
- At most one nudge a day, only in a good window.
- A `get_maintenance_guide` tool. Mark done with notes.
- Due dates go to the calendar (prompt 26).

Tests:
- Due calculation across active months.
- The one-a-day limit.
- Window timing.
- History recorded.

Commit when done.

---

## Milestone 6: Liaison and food (Phase 2)

### 34 · Liaison: relays, family group, alignment prompts
Status: [ ]
Depends on: 20, 29
Read first: "Module behaviour" → A (Relays, Alignment prompts); "How the family uses Themi"
(family group added in Phase 2).

Build:
- `relay_to_partner` tool with urgency:
    - urgent: now
    - today: by early evening at the latest
    - whenever: the next good window
  Delivery is formatted for the recipient (with their PDA settings).
- Family group setup: add the bot to a group, and an admin links it with a command. Only member
  messages in the group are processed.
- Alignment prompts: `flag_expectation_conflict` queues a short two-option question to the
  group, sent only when both partners are predicted receptive. Each person's tap is recorded and
  an agreed outcome can become a proposed rule.

Tests:
- Each urgency's delivery timing.
- Group linking and the non-member filter.
- An alignment prompt waits for both windows.
- The outcome leads to a rule proposal.

Commit when done.

### 35 · Meal reminders, takeout rescue, cart staging
Status: [ ]
Depends on: 27, 19
Read first: "Module behaviour" → D; "Integrations" → Safeway/DoorDash row.

Build:
- Meal reminders: log meals (text, plus a device hook), learn each person's usual gap (median
  ×1.3, with a floor and a ceiling), and nudge once per gap during waking hours with a
  suggestion from prompt 27.
- Takeout rescue: in the dinner window, if both partners are low, no meal has been logged in the
  last 3 hours and none has been staged today, pick a saved favourite under the remaining
  monthly budget and stage a DoorDash order (Tier 1, capped). It sends a store link and the
  items, and a person does the checkout.
- Spending comes from DoorDash receipts (prompt 23).
- Safeway cart staging: the grocery list becomes a staged cart message with item search links.
- Saved favourites are managed on the website.

Tests:
- Gap learning.
- One nudge per gap.
- All the takeout preconditions, including budget exhaustion.
- Spending updates from receipts.

Commit when done.

---

## Milestone 7: Research

### 36 · Research: CatGenie, automated calls, SMS
Status: [ ]
Depends on: 29
Read first: "Integrations" → CatGenie, vendor phone calls; "Decisions so far" (chat channel).

Do:
- CatGenie: research access options (official or community APIs, the app's traffic, email or
  push notifications). Write findings to `docs/research/catgenie.md` with sources. If there's a
  viable path, propose a connector prompt. Either way, implement the fallback: cleaning-schedule
  estimates plus a quick check-in task.
- Automated vendor calls: compare voice providers (cost per minute, conversational quality,
  setup) in `docs/research/voice-calls.md`.
- SMS as an extra channel: current Twilio pricing and US A2P 10DLC registration steps and costs,
  in `docs/research/sms.md`.
- Dishwasher: moved to its own prompt, H1 (2026-10-26), at Erin's request.
- End with a summary for the user and proposed follow-up prompts added to this file.

Commit when done.

### R2 · Research: Google Home
Status: [x] 2026-10-30
Depends on: none
From Michael's idea #21 ("google home integration", 2026-10-27). Find out what would help and
what's possible before building anything:
- What the family wants from it: asking Themi by voice ("Hey Google, ask Themi..."), Themi
  speaking announcements on a speaker, or reading the home's devices (thermostat, cameras,
  locks) as signals.
- What Google allows now: Google Home APIs, conversational actions (retired in 2023), the
  broadcast route, Matter. Accounts, costs, and whether a household app can use them
  unreviewed.
- The plan's rule that device connections read status only and never control anything:
  anything beyond reading needs the family's decision and a plan change first.

Notes (2026-10-30), research. Web sources checked that day; where nothing current confirmed a
detail, it says so.
- Asking Themi by voice ("Hey Google, ask Themi..."): there's no way in. Conversational
  Actions were retired in 2023, and Gemini for Home (now on the Nest speakers) has no
  public SDK for custom voice apps. "Gemini built in" (May 2026) is a program for hardware
  partners. What does work is GT1a: "Hey Google, add a task ..." lands in Google Tasks, and
  Themi takes it from there.
- Themi speaking on a speaker:
    - Broadcasting from a phone was removed in February 2024.
    - The Assistant SDK route (Home Assistant's `google_assistant_sdk` broadcast) is
      unofficial, and nothing confirmed it still works since Gemini replaced the Assistant.
    - Playing speech over Google Cast (text to speech, cast to the speaker) is what Home
      Assistant and Node-RED do. It needs Themi, or a small relay, on the home network:
      Cast is local, so a cloud server can't reach the speaker. Not confirmed on current
      Gemini speakers.
- Reading the home's devices as signals:
    - The Google Home APIs (Device, Structure, Automation) are phone-app SDKs for Android
      and iOS. A server can't call them without a companion app on a phone.
    - The Smart Device Management API (Device Access: $5 once, a consumer Google account)
      is a cloud REST API for Nest thermostats, cameras, doorbells and the Hub Max. It fits
      Themi's server and the plan's "read status only" rule.
- The plan's rule holds: device connections only read. Speaking on a speaker isn't control
  of a device, but it is a new way of reaching people, so it'd need the family's yes and a
  plan change (quiet hours, PDA phrasing, the outbox's timing).
- Decided (Michael, 2026-10-30): nothing more for now. The Google Tasks inbox (GT1a) covers
  voice. Speaking on a speaker and Nest devices as signals can come back as prompts.


### GT1a · Google Tasks as an inbox: voice-added items processed, then removed
Status: [x] 2026-10-30
Depends on: 21, 26
Asked by Michael, 2026-10-30. "Hey Google, add a task..." on the family's speakers (Gemini for
Home) lands in that person's Google Tasks. The family wants Google Tasks used as a
processing queue: Themi takes each new item as if that person had told it, then removes it.
Deleting a processed item needs no confirmation (decided 2026-10-30: the list is a queue).
Part of R2's question about Google Home; R2's other questions stay open.

Build:
- Linking asks for Google Tasks too (`https://www.googleapis.com/auth/tasks`); accounts linked
  before need linking again. The OAuth app needs the Tasks API and scope (Michael adds them).
- A Google Tasks client (tasks v1: lists, tasks, delete), like the Calendar client.
- A job every minute: each linked account with the scope, whose person is on Telegram, reads
  its default list ("My Tasks") for open items. Each new one is handled by the agent as that
  person's message ("Erin asked their Google speaker to add "milk" to Google Tasks"), and its
  reply goes to them in Telegram. Once handled, the item is deleted from Google Tasks.
- If no AI backend answers, the item stays and is tried again later (with a wait, so a busy
  model doesn't send a busy reply every minute). A failed delete is retried without handling
  the item again.

Tests:
- The client against a fake Google Tasks API.
- A voice item becomes a grocery item or a task, and is removed; one already handled isn't
  handled twice; an AI outage keeps the item; accounts without the scope are left alone.

Notes (2026-10-30):
- `TASKS_SCOPE` is in `LINK_SCOPES`, and `GoogleConfig.tasks_url` (`GOOGLE_TASKS_URL` for a
  fake). `themi.connectors.gtasks.TasksClient`: the open tasks on a list (paged, oldest
  first) and delete; a 401 refreshes the token once, and a 404 on delete counts as done.
- `themi.core.google_tasks.GoogleTasksInbox`, job `google_tasks.inbox` every minute (the API
  has no push). For each account with the scope whose person is on Telegram, each new open
  item on `@default` goes to `Agent.take_in`. That logs it as an inbound message (kind
  `google_task`, so the journal sees it), runs the usual turn, and replies in Telegram.
- The message reads 'Erin asked their Google speaker to add "Milk" to Google Tasks, due
  Friday 23 October, with the note "...". Take it as something they asked for.' The "asked
  ... to add" makes it count as asked for, so "milk" goes on the grocery list without a card,
  as if typed. Other actions go through their tiers as usual.
- Google keeps only a task's date, never its time, so a time said to the speaker doesn't
  reach Themi.
- Migration 0077 adds `google_task_inbox`: handled (answered, delete not done yet), removed,
  or waiting. A deleted item isn't a trust-tier action: the family decided the list is a
  queue, like the wall's sync clearing just-for-today items.
- If no AI backend answers, the item waits an hour, and that run stops. Done and empty items
  are left alone.
- My accounts says whether Google Tasks is allowed for each account.
- Not checked against the real API or a real speaker yet. Michael made a few test items by
  voice; once linked again they're handled within a minute.
- Setup: enable the Google Tasks API and add the `tasks` scope in the Google Cloud project,
  restart (applies 0077), and link each Google account again (`/link gmail`).

### GT1b · Themi's tasks on Google Tasks, kept apart from the inbox
Status: [x] 2026-10-30
Depends on: GT1a
Asked by Michael, 2026-10-30, if Themi's own tasks can be told apart from new voice items.
They can, two ways at once:
- Themi writes its tasks to a list of its own ("Themi"), never the default list GT1a empties.
- It keeps the Google id of every task it writes; an id it doesn't know is a new item,
  whichever list it's in.
Build: each person's open Themi tasks on their "Themi" list (title, due date); done in Google
(by voice: "mark call the plumber done") completes it in Themi, and done in Themi completes it
in Google. Check how Gemini for Home reads and completes tasks on a list that isn't the
default before relying on voice completion.

Notes (2026-10-30):
- `themi.core.google_tasks_list.GoogleTaskList`, run inside the `google_tasks.inbox` job, so
  writing a task and recognising it never race. For each person, their first linked account
  with Google Tasks allowed gets a "Themi" list (found by name, or made). Migration 0081
  adds `google_task_lists`, `google_task_links` (task, account, Google id, and whether it
  was deleted in Google), and `google_task_inbox.list_id`.
- What goes on the list: `open_for` (theirs, and shared ones), open, not repeating, and
  not off the wall's lists (the email audit's). Title and due date only; Google keeps no
  time.
- Each run:
    - Done in Google (shown with `showHidden`, so ticks in Google's own apps count): done
      in Themi.
    - New in Themi: written there. A title or date changed in Themi: patched; Themi's
      version wins, and edits made in Google aren't brought back.
    - Done in Themi: completed there. Cancelled, or not theirs any more: deleted there.
    - Deleted in Google: left off, not put back.
- The inbox now reads My Tasks and the Themi list, and skips the ids Themi wrote. Anything
  else there is a new item, handled and removed, as on My Tasks. Failed deletes are retried
  once per account per run.
- Not checked: how Gemini for Home reads and completes tasks on a list that isn't the
  default. If "mark ... done" by voice only reaches My Tasks, voice completion of Themi's
  tasks won't work (the app and the web still do).
- Setup: restart (applies 0081). Accounts already linked with Google Tasks need nothing
  more.

### GK1 · Groceries said to Google Home, from Google Keep
Status: [x] 2026-10-30
Depends on: G1, GT1a
Asked by Michael, 2026-10-30. "Hey Google, add 14oz can of tomatoes to my shopping list"
goes to Google Keep, never Google Tasks, so GT1a doesn't see it. Google ended other list
apps for the Assistant on 2023-06-20; Gemini's lists work only with Keep. Google's Keep API
is Workspace-only: a personal account asking for `keep.readonly` gets "Error 400:
invalid_scope" (tried 2026-10-30). The family chose the unofficial route, as with
OurGroceries.

Build:
- An optional dependency, `gkeepapi` (MIT, unofficial; `pip install 'themi[keep]'`), imported
  only when the sync first runs. It signs in with a Google master token: a powerful
  credential that doesn't expire. Kept encrypted per person, never logged, used only for
  Keep. Without the library, the sync logs and waits.
- Linking, per person, from the command line: `themi keep link <name>` asks for the Google
  address and the `oauth_token` cookie from Google's EmbeddedSetup page, exchanges it for a
  master token (gpsoauth), checks it by reading Keep, shows the lists found, and stores the
  token and which list to watch (default "Shopping list"). `themi keep unlink <name>`.
- A job every 2 minutes: for each linked person, the watched list's unchecked items go on
  Themi's grocery list as theirs, like items added in the OurGroceries app (G1: what the
  family adds in its own lists isn't staged), then are checked off in Keep. An item already
  needed isn't added twice. A failed check-off is retried without adding again; an item
  someone unchecks in Keep is new again.
- Keep failing (sign-in, network, a change at Google) is logged with backoff up to an hour,
  per person, and never blocks the grocery list.

Tests:
- The sync against a fake Keep: new items added and checked off, already-needed items not
  doubled, a failed check-off not re-added, an unchecked item added again, Keep down with
  backoff, people without Keep left alone, the library missing.
- Linking: the token stored encrypted, a wrong list name refused, unlink.

Notes (2026-10-30):
- `themi.connectors.gkeep`: `GKeepAccount` wraps gkeepapi 0.17 in threads (it's synchronous),
  signs in once and syncs incrementally after; any library error drops the session so the
  next call signs in again. `exchange_token` uses gpsoauth (it comes with gkeepapi). Lists
  are matched by title, ignoring case; trashed lists are skipped.
- `themi.core.keep_groceries`: `KeepLinks` (migration 0082: `keep_accounts`, the master token
  encrypted with the device id it was made for; `keep_items`, what was taken) and
  `KeepGroceries`, job `groceries.keep` every 2 minutes, wired whenever Themi runs; it does
  nothing until someone links. Items go straight onto the list with `GroceryList.add`, like
  the OurGroceries mirror's, so no card; the mirror then sends them to OurGroceries.
  Checked off, not deleted, so Keep keeps a trail. An item with no name Themi can keep (all
  emoji) is left in Keep until it's edited.
- Linking reads the list before saving, and says how many items are waiting; a wrong list
  or a bad cookie saves nothing. A re-link takes effect at the next run, no restart.
- No message is sent when an item comes in, as with OurGroceries.
- Not checked against the real Keep yet: the first `themi keep link` is the test.
- Setup: `pip install -e '.[keep]'`, restart (applies 0082), then `themi keep link <name>`
  for Erin and Michael. Erin's Google account also lacks the Google Tasks scope (GT1a), so
  "add a task" in her voice isn't read until she links again.

### GK2 · Themi's grocery list shown in Keep, both ways
Status: [x] 2026-10-30
Depends on: GK1
Asked by Michael, 2026-10-30, after GK1 worked: the list Themi keeps should appear in Keep
too. Decided: Themi always wins when both sides changed.

Build:
- Each linked person's watched Keep list shows Themi's grocery list (the needed items),
  unchecked. With two people linked, both lists show it; a change in either counts.
- From Keep, as with OurGroceries (G1): an unchecked item Themi doesn't know is added (the
  speaker, or someone typing in Keep) and stays there as that item, no longer checked off;
  one already on the list is a duplicate and is deleted from Keep. Checking an item off is
  "bought"; deleting it is "removed"; unchecking one checked off is "needed again".
- To Keep: an item needed in Themi with no item in Keep is added; bought in Themi is checked
  off; removed in Themi is deleted.
- Themi wins: a Keep change counts only if Themi hasn't changed that item since the last
  sync. Keep can drop a write (seen 2026-10-30: a check-off that didn't stick), so Themi's
  writes stay unconfirmed until a read shows them; an unconfirmed write that isn't there is
  made again, never read as someone's change.

Tests:
- Speaker items added and kept; duplicates deleted; checked off in Keep is bought, deleted is
  removed, unchecked is needed again; Themi's adds, buys and removes reach Keep.
- Themi wins over a Keep change to the same item; a dropped add or check-off is made again,
  not taken as a delete or an uncheck; two people's lists stay in step.

Notes (2026-10-30):
- Migration 0083 rebuilds `keep_items`: each Keep item Themi knows, `shown` (stands for a
  `grocery_list` row while it's needed), `done` (checked off for a bought item) or
  `skipped`, and `confirmed` (a read has shown Themi's last write). GK1's rows are dropped;
  the items they name are checked off in Keep and stay so. Re-linking forgets them too.
- `KeepAccount` is now `items` (all, with `checked`) and `apply` (adds, check-offs and
  deletes in one gkeepapi sync, returning the new ids). GK1's `unchecked`/`check_off` went.
- `KeepGroceries.sync`: pull, then push, then one write. Pull: unknown unchecked items are
  new (a duplicate of a needed item already shown is deleted); a shown item checked off
  while still needed is bought (and the pantry has it, as with OurGroceries); a confirmed
  shown item gone is removed; a confirmed done item unchecked is needed again; an
  unconfirmed one is written again instead. Push, in list order: needed with no shown
  item, added; shown but no longer needed, checked off if bought, else deleted.
- Themi wins because Keep's changes are read against the row Themi still has: once Themi
  has bought or removed a row, a Keep change to its item is overwritten by the push.
- Unknown items already checked off (Keep's history) are left alone. Checked-off items
  aren't cleared from Keep; Keep folds them away.
- A failed write keeps what was read from Keep; the write is worked out again next time.
- With two people linked, a change in one Keep reaches the other on its next run.
- Setup: restart (applies 0083). The first sync puts the whole grocery list into each
  linked Keep list.

