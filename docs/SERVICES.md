# Connecting services

Every service below is optional. Turn on the ones your household uses from the **Modules**
page on Themi's website: each module has these same steps as its guide, beside the boxes
its values go in (secrets are kept encrypted). The sections here also name the `.env`
variables, for setting a value on the server instead ([ENVIRONMENT.md](ENVIRONMENT.md)
lists them all). A value set on the server wins, and the Modules page offers to move it
into Themi.

New to Themi? Start with the [installation guide](INSTALL.md).

- [Google sign-in, Gmail, Calendar, Tasks, Docs and Sheets](#google-sign-in-and-gmail-google-cloud-setup)
- [OurGroceries](#ourgroceries-optional)
- [Cozyla to-do lists, chores and routines](#cozyla-to-do-lists-optional-a-trial)
- [The dishwasher (Home Connect)](#the-dishwasher-through-home-connect-optional)
- [The washer and dryer (LG ThinQ)](#the-washer-and-dryer-through-lg-thinq-optional)
- [The robot vacuum (Roborock)](#the-robot-vacuum-through-roborock-optional)
- [The pet feeders (SmartLife / Tuya)](#the-pet-feeders-through-smartlife--tuya-optional)
- [The litter box (CatGenie)](#the-litter-box-through-catgenie-optional)
- [Groceries said to Google Home (Google Keep)](#groceries-said-to-google-home-through-google-keep-optional-a-trial)

Other modules (Slack, weather, parcels, the oven, Spotify, web search, travel times, the
Safeway cart and the AI providers) carry their setup steps only on their Modules page
guide.

## Google sign-in and Gmail (Google Cloud setup)

Each family uses its own Google Cloud project. It's free, and takes about 15 minutes.

1. **Project.** At <https://console.cloud.google.com>, create a project (for example
   "Themi Household").
2. **APIs.** Under *APIs & Services → Library*, enable the **Gmail API**, the
   **Google Calendar API**, the **Google Tasks API**, for the cookbook (RC1a) the
   **Google Docs API**, the **Google Drive API** and the **Google Picker API**, and for
   expense sheets (EX4a) the **Google Sheets API**.
3. **Consent screen.** Under *Google Auth Platform → Branding*, give the app a name
   ("Themi") and a support email. Under *Audience*, choose **External**.
4. **Scopes.** Under *Data Access*, add `openid`, `.../auth/userinfo.email`,
   `https://www.googleapis.com/auth/gmail.modify`,
   `https://www.googleapis.com/auth/calendar.events`,
   `https://www.googleapis.com/auth/calendar.calendarlist.readonly` (to find the "Themi"
   calendar), `https://www.googleapis.com/auth/calendar.app.created` (to make it if
   it's missing), `https://www.googleapis.com/auth/tasks` (the Google Tasks inbox) and
   `https://www.googleapis.com/auth/drive.file` (only the files someone picks for Themi,
   such as the cookbook, or that it makes).
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
7. **Keys.** Put the client id and secret on the Modules page, under **Google
   accounts**, then press **Restart** there. (`GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET` in `.env` work too.)
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
12. **The family cookbook (RC1a).** Themi reads the family's recipe doc and can add to it,
   but with `drive.file` it can open only a doc someone picks in Google's file picker. For
   the picker: under *APIs & Services → Credentials*, create an **API key** restricted to
   the Google Picker API (and to the site's address under *Website restrictions*); copy the
   project **number** from the project's *Dashboard*; in the OAuth client add
   `<THEMI_PUBLIC_URL>` (the Funnel address, no path) as an **Authorized JavaScript origin**.
   Put them in `.env` as `GOOGLE_PICKER_API_KEY` and `GOOGLE_PROJECT_NUMBER`, restart, then
   on *Accounts* open the account's *Choose the family cookbook* and pick the doc. An
   account linked before this needs linking again (with Google Drive ticked).
13. **Expense sheets in Google Sheets (EX4a).** With the Google Sheets API on, Themi makes
   each expense spreadsheet in the linked account a person chooses and keeps it up to date.
   It uses the same `drive.file` scope, so it can open only the spreadsheets it made. An
   account without Google Drive allowed shows *Link again for expense sheets* on *Accounts*;
   nothing else changes for it.

To try the flow without a Google project, run the fake Google with
`.venv/bin/python -m tests.fakes.google_oauth` and copy the settings it prints into `.env`.
Its sign-in page asks which address to pretend to be.

## OurGroceries (optional)

Themi keeps its own grocery list, and the website's dashboard shows it. To see it in the
OurGroceries app as well, put the account's login in `.env` as `OURGROCERIES_USERNAME` and
`OURGROCERIES_PASSWORD`, and the shared list's name as `OURGROCERIES_LIST` (default
"Groceries"), then restart. Outside Docker, install the library first with
`pip install -e '.[ourgroceries]'`. It's unofficial, so if OurGroceries changes, the mirror
logs the problem and keeps retrying while Themi's own list carries on.

## Cozyla to-do lists (optional, a trial)

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

## The dishwasher, through Home Connect (optional)

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

## The washer and dryer, through LG ThinQ (optional)

An LG washer and dryer on the ThinQ app can tell Themi when they run and finish, through
LG's official ThinQ Connect API. Themi only reads them, and a token with just the two "view"
permissions below couldn't control them anyway.

1. At [connect-pat.lgthinq.com](https://connect-pat.lgthinq.com), signed in with the LG
   account the appliances are on, add a personal access token with "View all devices" and
   "View all device statuses".
2. As an admin, open the Family page, paste it under **Washer and dryer** with the country
   it was made for, and press **Link LG ThinQ**. Themi lists what it found; set each one to
   Washer, Dryer or Not used.
3. For updates as they happen, install the MQTT library (`pip install -e '.[thinq]'`) and
   restart (the Docker image includes it). Without it Themi reads the appliances every 5
   minutes, which works too.

When the washer finishes, whoever has more room gets a nudge half an hour later to move the
load (Later asks again in an hour); the dryer starting settles it, and takes back a nudge not
yet sent. A load left longer than the fresh hours on the Family page (8 by default) gets a
rewash suggestion instead, timed to finish when that person has room.
"/pause laundry" holds these nudges for a while.

## The robot vacuum, through Roborock (optional)

A Roborock vacuum (built for the S8 MaxV Ultra) can tell Themi when it needs a person.
Roborock has no official API, so Themi uses the unofficial `python-roborock` library, the
one Home Assistant's Roborock integration uses. It signs in with the Roborock app account
and talks to the robot over the home network when it can, through Roborock's cloud
otherwise. The library may break when Roborock changes things; Themi then logs it and the
vacuum goes quiet until it's fixed.

1. Install the library: `pip install -e '.[roborock]'`, and restart. (The Docker image
   includes it.)
2. As an admin, open the Family page, enter the Roborock app's email under **Robot
   vacuum**, press **Send code**, then enter the code Roborock emails and press **Link
   Roborock**. The login it returns is kept encrypted.

When it gets stuck, jammed, runs the dock's clean water out, fills the dirty-water tank,
loses its dustbin or doesn't make it back to its dock, whoever has more room gets a chore and
a nudge 5 minutes later (half an hour for "not back on its dock"), naming the room when its
map says. If the robot sorts itself out first, nothing is sent. Once it's sorted, Themi asks
to clear its alert in the app and send it back to its dock; turn on "Clear the vacuum's alert
and send it back to its dock" under "What Themi does alone" to skip asking. A part nearly worn
out (filter, brushes, the dock's filter) becomes a chore too. "/pause vacuum" holds these
nudges for a while. If the sign-in stops working, the admin hears once; link it again.

## The pet feeders, through SmartLife / Tuya (optional)

Feeders on the SmartLife (or Tuya Smart) app can tell Themi when their food runs low or out,
or something's stuck, through a cloud project on Tuya's developer platform. Themi only reads
them; it never feeds.

1. Sign up at [platform.tuya.com](https://platform.tuya.com) and create a cloud project
   (Cloud, Development): development method "Smart Home", and the data centre the app
   account lives in ("Western America" for an account made in the US). Keep the API
   services it offers (IoT Core and Authorization Token Management are the ones Themi uses).
2. In the project's **Devices** tab, **Link App Account**, and scan the QR code it shows
   from the SmartLife app (Me, then the scan icon). The feeders appear in the project.
3. Still under Devices, set the feeders' **control instruction mode** to "DP Instruction"
   if it offers it, so their own data points (a fault code, say) reach Themi too.
4. From the project's Overview, copy the **Access ID** and **Access Secret**. As an admin,
   open the Accounts page, paste them under **Pet feeders** with the same data centre, and
   press **Link Tuya**. Feeders map themselves; anything else (a water fountain) is "Not
   used" until set. The secret is kept encrypted.
5. Tuya's free IoT Core plan lasts a month at a time and has to be extended on Tuya's site
   (it's free to extend). When it lapses, the admin hears once; extend it, then link again.

Each feeder is read every 10 minutes. Food running low (20% or under, when the feeder says
how much is left) or out, food stuck, or another fault becomes a chore for whoever has more
room, with a nudge 10 minutes later; one sorted in the meantime sends nothing, and the feeder
showing it's sorted closes the chore. Out of food or stuck can't wait for tomorrow, so those
nudges aren't held by the daily limit. "/pause feeders" holds them for a while. Asked "has
the cat been fed?", Themi reads the feeder and its last feeding.

Feeders name their data points differently from model to model, so the mapping was written
from Tuya's standard feeder and common shapes, not from these feeders. The Accounts page
lists each feeder's data points; to send them for a proper mapping, run
`themi tuya capture --out tuya-captures` (in Docker: `docker compose exec themi themi tuya
capture --out /data/tuya-captures`). The files leave out the devices' ids, keys and names.

## The litter box, through CatGenie (optional)

A CatGenie A.I. can tell Themi how it's doing: cleaning or not, its sani-solution and any
error. CatGenie has no official API, so Themi talks to the CatGenie app's own cloud
(PetNovations) the way the community client
[kclif9/catgenie-api](https://github.com/kclif9/catgenie-api) found it works. It may stop
working when they change things; the admin then hears once, and the litter box goes quiet.
Themi only reads it; it never starts, stops or changes a clean.

1. As an admin, open the Accounts page, enter the phone number the CatGenie app signs in
   with under **Litter box**, and press **Send code**.
2. Enter the code that's texted to it and press **Link CatGenie**. Themi keeps the sign-in
   (encrypted), not the number.

The litter box is read every 10 minutes. An error (on the box, or an alert the app was sent),
or the sani-solution running low (20% or under) or out, becomes a chore for whoever has more
room, with a nudge 10 minutes later; one sorted in the meantime sends nothing, and the box
showing it's sorted (the error gone, a clean after the alert, a new cartridge) closes the
chore. An error or no sani-solution stops it cleaning, so those nudges aren't held by the
daily limit. "/pause litter" holds them for a while. If the sign-in stops working, the admin
hears once; link it again. Asked "is the litter box ok?" or "how much sani-solution is
left?", Themi reads it.

The CatGenie can't tell how many granules are left, so Themi counts its cleans instead: set
**Top up the granules every _ cleans** under the litter box on the Accounts page, and a
chore comes round each time that many have gone by. Marking it done starts the count again.
Leave it blank for none.

Nobody has published what the CatGenie's error codes mean, so for now each one is shown in
plain words from the code itself. To send real ones for a proper mapping, run
`themi catgenie capture --out catgenie-captures` (in Docker: `docker compose exec themi
themi catgenie capture --out /data/catgenie-captures`), ideally a few times as the box shows
different things: cleaning, the cartridge low, the dome off, an error. The files leave out
the box's ids and names and the account's number.

## Groceries said to Google Home, through Google Keep (optional, a trial)

"Hey Google, add tomatoes to my shopping list" puts them in Google Keep. Google's Keep API
isn't open to personal accounts, so Themi reads Keep with the unofficial `gkeepapi` library
and a master token per person. That token can do nearly anything to its Google account and
doesn't expire: Themi keeps it encrypted and uses it only for Keep. The library may break if
Google changes Keep; Themi then logs it and retries, and the grocery list carries on.

1. Install the library: `pip install -e '.[keep]'`. (The Docker image doesn't include it;
   add `keep` to the `pip install` line in the Dockerfile.)
2. For each person, run `themi keep link <name>` (add `--list "<name>"` if their list isn't
   called "Shopping list") and follow its steps: sign in at Google's EmbeddedSetup page and
   paste the `oauth_token` cookie. Themi needn't be restarted.

Every 2 minutes, each linked person's Keep list and the grocery list are kept in step, both
ways. What the speaker (or anyone) adds in Keep joins the grocery list as theirs; checking
an item off in Keep means bought, deleting it means removed. Themi's own changes show in
Keep the same way. When both sides changed an item, Themi's change wins. The first sync
puts the whole grocery list into Keep. `themi keep unlink <name>` stops it; removing the
"Android" sign-in on the Google account's security page revokes the token.

