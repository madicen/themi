# Themi

Themi is a household assistant that one family runs on its own server. Each person chats
with it through Telegram, and it handles the background admin: laundry timing, groceries,
email triage, maintenance and meals. It times every prompt to when each person has the
energy for it, and phrases prompts so they never feel like demands.

- Design: [Themi Build Plan (V1)](https://claude.ai/artifact/PWX3iYKmbKy1UmCQrVF2Z1)
- Build order and progress: [docs/BUILD_PROMPTS.md](docs/BUILD_PROMPTS.md)

## Development setup

Needs Python 3.12+ and [jj](https://jj-vcs.github.io/jj/) (the repo is a colocated jj/git repo).

```sh
make venv        # create .venv (pin an interpreter with VENV_PYTHON=/path/to/python3.x)
make install     # editable install with dev tools
make test        # unit tests, the fast loop while coding
make test-all    # unit + integration + scenarios (what CI runs)
make lint        # ruff, pyright, and the clock check
```

`make test-live` and `make evals` talk to real services and need test-account keys;
they never run by default.

### Rules worth knowing

- Read time only through `themi.clock` (`tools/check_clock.py` enforces it), so tests can
  freeze and advance it.
- The default test run makes no real network calls; fakes live in `tests/fakes`.

## Running Themi

1. Copy `.env.example` to `.env`. Fill in `THEMI_SECRET_KEY` (from `themi keygen`) and
   `TELEGRAM_BOT_TOKEN` (from @BotFather). Back up the secret key: without it, stored tokens
   and keys can't be decrypted.
2. Run `themi init` once to create the family and its first admin. Then send the bot
   `/start <code>` from Telegram.
3. Run `themi run`. This starts the bot, the scheduler and the website (`/health` on
   port 8080).

### With Docker

```sh
docker compose run --rm themi init     # first time only
docker compose up --build -d           # start
docker compose run --rm themi invite <name>
```

The database lives in the `themi-data` volume. `docker compose down` stops Themi gracefully:
the message or job in progress finishes first. `tools/smoke_container.sh` builds the image and
checks it starts, reports healthy, and stops cleanly. CI runs it on every push.
