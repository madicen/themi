# Developing Themi

How to work on Themi's code: setting up, running the tests, and trying Themi on your own
computer without a bot token or real accounts. To run Themi for a household, see the
[installation guide](INSTALL.md) instead.

- Design: [Themi Build Plan (V1)](https://claude.ai/artifact/PWX3iYKmbKy1UmCQrVF2Z1), and the
  plans [CLAUDE.md](../CLAUDE.md) lists for each area
- Build order and progress: [BUILD_PROMPTS.md](BUILD_PROMPTS.md)

## Setting up

Needs Python 3.12+ and [jj](https://jj-vcs.github.io/jj/) (the repo is a colocated jj/git repo).

```sh
make venv        # create .venv (pin an interpreter with VENV_PYTHON=/path/to/python3.x)
make install     # editable install with dev tools
make test        # unit tests, the fast loop while coding
make test-all    # unit + integration + scenarios (what CI runs on a pull request)
make lint        # ruff, pyright, and the clock check
```

`make test-live` and `make evals` talk to real services and need test-account keys;
they never run by default.

CI splits the tests across runners, balanced by the times in `.test_durations`. After
adding or speeding up a lot of tests, run `make durations` and commit the file. New tests
still run before you do; the halves just get less even.

## Trying Themi on this computer

`make dev` runs Themi against a Telegram simulator, so you can chat with it without a bot
token. Open <http://localhost:8090>, pick a person and type. You can tap buttons, react with
✅ or 💤, and skip Themi's clock ahead to see scheduled nudges. The header's *Website* link
opens the management site signed in as that person.

- Dev data lives in `data/dev/`, with its own secret key, apart from the real database.
  `make dev-reset` starts over. Its website is on port 8081 (`THEMI_DEV_HTTP_PORT`), so it
  can run alongside a real `themi run` on 8080.
- The first run seeds Erin and Husband, both paired, and puts `GEMINI_API_KEY` from `.env`
  on their default AI backend. Without a key, Themi replies that setup is needed. You can also
  add a key on the website's AI page.
- To try pairing: `make dev-invite NAME=Sam`, then send the `/start` code as *Someone new*.
- *Copy session* copies the conversations and Themi's log as text, to paste into a Claude
  session. *New session* marks where the next copy starts.
- Every outside service is played by its test fake: Gmail, Calendar and Tasks for
  `erin@gmail.com` and `husband@gmail.com`, Keep, the wall, OurGroceries, an LG washer and
  dryer, a Bosch dishwasher, a Roborock and two SmartLife pet feeders. They're linked on
  the first run and kept in `data/dev/fakes.json`. `make dev FAKES=0` runs without them.
  Replies use real Gemini.
- The *Control panel* (<http://localhost:8090/control>, beside the chat on a wide screen)
  makes things happen outside the chat: an email arrives, an event is added or moved, a
  to-do is ticked on the wall, the washer finishes, the robot gets stuck, a feeder runs low
  or jams. Themi looks at once, and each action shows in the chat and in *Copy session*.
  Each section can also make its service fail (busy, offline, signed out), the Safeway helper answers cart jobs
  as the extension would, and *Scenes* run a whole day of these with the clock skipped
  between them (`tools/dev/scenes.py`).
- `make dev-prod` runs the same way on a fresh copy of the Pi's data, in `data/dev-prod/`
  (over ssh to `THEMI_PI`, default `themi@themi`). `make dev-prod BACKUP=latest` copies from
  the encrypted backups instead, and `KEEP=1` reuses the last copy. The copy is cleaned
  first: no tokens, keys or sign-ins, Gmail switched off, and member 1 and 2 are the
  simulator's Erin and Husband. It holds the family's real messages and email, so
  `make dev-reset` deletes it too.

`make fresh` runs a brand-new Themi as someone installing it would meet it: a claim code in
its log, the key page, an empty Modules page, at <http://localhost:8080>. Its data is in
`data/fresh/` and it doesn't read `.env`. `make fresh-reset` (with it stopped) starts it over.

## Rules worth knowing

- Read time only through `themi.clock` (`tools/check_clock.py` enforces it), so tests can
  freeze and advance it.
- The default test run makes no real network calls; fakes live in `tests/fakes`.

The full list (the outbox, the trust tiers, the AI router, secrets) is under "Rules the code
must keep" in [CLAUDE.md](../CLAUDE.md).

## Bug reports and ideas from the chat

Anyone in the family can send `/bug <what happened>` or `/idea <what they'd like>`, or just
say "that's a bug..." or "it'd be nice if...". Using Telegram's Reply on the message that went
wrong marks it. Each report keeps the recent conversation, what was waiting on the person,
their settings, their AI backend and Themi's recent log lines.

```sh
themi feedback              # new reports as Markdown, to paste into a Claude session
themi feedback --done 3 4   # mark reports reviewed
themi feedback --all        # include reviewed ones
```

