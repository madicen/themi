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

### Trying Themi on this computer

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
- Only Telegram is simulated. Replies use real Gemini, and Google and OurGroceries are off.

### Rules worth knowing

- Read time only through `themi.clock` (`tools/check_clock.py` enforces it), so tests can
  freeze and advance it.
- The default test run makes no real network calls; fakes live in `tests/fakes`.

## Running Themi

1. Copy `.env.example` to `.env`. Fill in `THEMI_SECRET_KEY` (from `themi keygen`) and
   `TELEGRAM_BOT_TOKEN` (from @BotFather). Back up the secret key: without it, stored tokens
   and keys can't be decrypted.
2. Run `themi init` once to create the family and its first admin. Then send the bot
   `/start <code>` from Telegram. `themi init` and `themi invite <name>` also print a
   `https://t.me/<bot>?start=<code>` link: opening it on a phone and pressing Start sends
   the code, so you can text the link to the person you're inviting.
3. Run `themi run`. This starts the bot, the scheduler and the website (`/health` on
   port 8080).

### Bug reports and ideas from the chat

Anyone in the family can send `/bug <what happened>` or `/idea <what they'd like>`, or just
say "that's a bug..." or "it'd be nice if...". Using Telegram's Reply on the message that went
wrong marks it. Each report keeps the recent conversation, what was waiting on the person,
their settings, their AI backend and Themi's recent log lines.

```sh
themi feedback              # new reports as Markdown, to paste into a Claude session
themi feedback --done 3 4   # mark reports reviewed
themi feedback --all        # include reviewed ones
```

### Google sign-in and Gmail (Google Cloud setup)

Each family uses its own Google Cloud project. It's free, and takes about 15 minutes.

1. **Project.** At <https://console.cloud.google.com>, create a project (for example
   "Themi Household").
2. **APIs.** Under *APIs & Services → Library*, enable the **Gmail API**, the
   **Google Calendar API** and the **Google Tasks API**.
3. **Consent screen.** Under *Google Auth Platform → Branding*, give the app a name
   ("Themi") and a support email. Under *Audience*, choose **External**.
4. **Scopes.** Under *Data Access*, add `openid`, `.../auth/userinfo.email`,
   `https://www.googleapis.com/auth/gmail.modify`,
   `https://www.googleapis.com/auth/calendar.events`,
   `https://www.googleapis.com/auth/calendar.calendarlist.readonly` (to find the "Themi"
   calendar), `https://www.googleapis.com/auth/calendar.app.created` (to make it if
   it's missing) and `https://www.googleapis.com/auth/tasks` (the Google Tasks inbox).
5. **Publish, unverified.** Under *Audience*, press **Publish app** and don't submit it
   for verification. Google shows an "unverified app" warning at sign-in ("Advanced", then
   "Go to Themi" continues). `gmail.modify` is a restricted scope, so an unverified app can
   be used by at most 100 accounts over the project's life. That's far more than one family
   needs. Leaving the app in **Testing** instead works too, but then Google expires the
   Gmail tokens every 7 days, and everyone has to link again.
6. **Client.** Under *Clients*, create an OAuth client of type **Web application**. Add the
   authorized redirect URI `<THEMI_PUBLIC_URL>/auth/google/callback`. When testing on your
   own machine, set `THEMI_PUBLIC_URL=http://localhost:8080` and use
   `http://localhost:8080/auth/google/callback`. Google only accepts plain `http` for
   `localhost`, not for `127.0.0.1` or other addresses.
7. **Keys.** Put the client id and secret in `.env` as `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET`, then restart Themi.
8. **Sign-in addresses.** On the website's *Family* page, an admin enters each person's Google
   address. Only those addresses can use "Sign in with Google". A person's first linked
   Gmail becomes their sign-in address if they don't have one yet.
9. **Linking.** Each person sends `/link gmail` to the bot, or uses *My accounts → Link a Gmail
   account* on the website. They can link as many accounts as they like. *Unlink* revokes
   Themi's access at Google too.
10. **Family calendar.** Dated tasks go on a calendar called "Themi" on an admin's linked
   account, after a yes. On the *Family* page an admin can pick the account and the
   calendar's name. Themi uses an existing calendar with that name, or makes one; either
   way, add it to Cozyla once so the events show there. An account linked before the
   calendar scopes existed needs linking again; the *Family* page says so.
11. **Google Tasks inbox.** What someone adds by voice ("Hey Google, add a task...") lands in
   their Google Tasks. Each minute Themi takes new items from their default list ("My
   Tasks") as if they'd sent them, answers in Telegram, and deletes them there: the list is
   a queue. An account linked before this needs linking again; *My accounts* says so.

To try the flow without a Google project, run the fake Google with
`.venv/bin/python -m tests.fakes.google_oauth` and copy the settings it prints into `.env`.
Its sign-in page asks which address to pretend to be.

### OurGroceries (optional)

Themi keeps its own grocery list, and the website's dashboard shows it. To see it in the
OurGroceries app as well, put the account's login in `.env` as `OURGROCERIES_USERNAME` and
`OURGROCERIES_PASSWORD`, and the shared list's name as `OURGROCERIES_LIST` (default
"Groceries"), then restart. Outside Docker, install the library first with
`pip install -e '.[ourgroceries]'`. It's unofficial, so if OurGroceries changes, the mirror
logs the problem and keeps retrying while Themi's own list carries on.

### Cozyla to-do lists (optional, a trial)

Themi can keep the Cozyla wall calendar's to-do lists in step with its one-off tasks, both
ways: added, ticked off or back, deleted, renamed, reassigned or given a new date on either
side. Repeating chores stay off them. Cozyla has no official API; this uses the one its
tablet apps use, which may change or break, and may conflict with Cozyla's terms, so use the
family's own account.

1. Put the family's Cozyla ID in `.env` as `COZYLA_EMAIL` and `COZYLA_PASSWORD`.
2. Run `themi cozyla check`. It signs in, changes nothing, and lists the to-do lists and
   members (add `--titles` to see the open to-dos on the chosen list).
3. Set `COZYLA_TODO_LIST` to the main list, and restart. Themi's tasks go there unless
   someone names another list ("put it on Things to Cook").

What becomes a Themi task: everything on the main list, and anything on another list that's
assigned to someone. A to-do assigned to the family member (for example "Madicen Family") is
shared: on both lists, and either of you can tick it off. Unassigned items on other lists
stay lists; "add lasagna to Things to Cook" just adds it there. The first sync links to-dos
that match open tasks by title, and nudges the assigned ones gently, a few at a time.

Members are matched by first name. Leave `COZYLA_TODO_LIST` empty to stop syncing.

With `COZYLA_CHORES=yes`, Themi also runs the wall's chore chart. Its chores are written
there and kept that way (an edit on the wall is put back, so change chores in Themi), chores
only on the wall come into Themi first, and a tick on either side counts on both. It reads
the wall's routines too: after the morning, and an hour before quiet hours, anyone whose
routines for that part of the day aren't all done gets one message with a button for each.
Themi's check-ins (like a run on set days) show on the wall as that person's routine.

### The dishwasher, through Home Connect (optional)

A Bosch (or Siemens, or another Home Connect) dishwasher can tell Themi when it runs. Themi
only reads whether it's running; it never controls it.

1. At [developer.home-connect.com](https://developer.home-connect.com), register an
   application with the Authorization Code Grant Flow and the redirect URI
   `<THEMI_PUBLIC_URL>/auth/home-connect/callback`.
2. Put its client id and secret in `.env` as `HOME_CONNECT_CLIENT_ID` and
   `HOME_CONNECT_CLIENT_SECRET`, and restart.
3. As an admin, open the Family page and press **Link Home Connect**. The dishwasher shows
   under Appliances.

When a cycle starts, Themi offers to check off the dishwasher on the wall's routines, and
any open Themi task about the dishwasher, to whoever's item it is. Turning on "Check off the
dishwasher routine when the dishwasher starts" on the website's "What Themi does alone" page
makes that automatic. Each evening, a week with fewer runs than usual feeds the energy model
as device activity, as words, never a score.

### Groceries said to Google Home, through Google Keep (optional, a trial)

"Hey Google, add tomatoes to my shopping list" puts them in Google Keep. Google's Keep API
isn't open to personal accounts, so Themi reads Keep with the unofficial `gkeepapi` library
and a master token per person. That token can do nearly anything to its Google account and
doesn't expire: Themi keeps it encrypted and uses it only for Keep. The library may break if
Google changes Keep; Themi then logs it and retries, and the grocery list carries on.

1. Install the library: `pip install -e '.[keep]'`.
2. For each person, run `themi keep link <name>` (add `--list "<name>"` if their list isn't
   called "Shopping list") and follow its steps: sign in at Google's EmbeddedSetup page and
   paste the `oauth_token` cookie. Themi needn't be restarted.

Every 2 minutes, each linked person's Keep list and the grocery list are kept in step, both
ways. What the speaker (or anyone) adds in Keep joins the grocery list as theirs; checking
an item off in Keep means bought, deleting it means removed. Themi's own changes show in
Keep the same way. When both sides changed an item, Themi's change wins. The first sync
puts the whole grocery list into Keep. `themi keep unlink <name>` stops it; removing the
"Android" sign-in on the Google account's security page revokes the token.

### In the cloud

`docs/DEPLOY.md` covers a small cloud server, Tailscale Funnel for the website, nightly
encrypted backups (`themi backup`, `themi restore`), upgrades and a restore drill.

### With Docker

```sh
docker compose run --rm themi init     # first time only
docker compose up --build -d           # start
docker compose run --rm themi invite <name>
```

The database lives in the `themi-data` volume. `docker compose down` stops Themi gracefully:
the message or job in progress finishes first. `tools/smoke_container.sh` builds the image and
checks it starts, reports healthy, and stops cleanly. CI runs it on every push.
