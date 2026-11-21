# What Themi does

A tour of Themi by area. Every area is a module (or a few) that can be turned on or off from
the Modules page, so a household runs only what it uses. The [README](../README.md) has the
pictures; this page has the detail.

- [How Themi talks](#how-themi-talks)
- [Your day](#your-day)
- [Tasks, chores and routines](#tasks-chores-and-routines)
- [Email](#email)
- [Food: groceries, meals and cooking](#food-groceries-meals-and-cooking)
- [The house](#the-house)
- [Getting things done together](#getting-things-done-together)
- [Trust: what Themi does on its own](#trust-what-themi-does-on-its-own)
- [Privacy and your data](#privacy-and-your-data)
- [Not just for families](#not-just-for-families)

## How Themi talks

- **Telegram** for the family, **Slack** DMs for a work Themi, and a chat on the website.
  Each person has their own chat; a family group works too ("Themi, ...").
- **Timed to each person's energy.** Themi learns when someone tends to have room for
  things (from their calendar, how busy their list is, how they react to messages and what
  they tell it) and holds non-urgent prompts for a good moment. It never shows anyone a
  score; the private "How Themi sees your week" page says it all in words.
- **Never a demand.** Every message passes a check that softens commands and pressure
  ("You need to..." becomes a question with an easy way out). How strict is up to each
  person.
- **A daily budget.** Only a few unasked-for messages a day. Urgent things (a reminder you
  set, a medicine, "time to leave", an urgent email) always come through.
- **When it's too much**: "today's too much" gets a few things now and the rest spread over
  the coming days. **Burnout mode** holds everything, makes no demands, and quietly passes
  urgent things to a partner. **Breaks** pause Themi and end with a gentle question.
- **Voice notes, photos and PDFs.** A photo of a school flyer becomes an event; a photo of a
  recipe becomes a recipe; a photo of a to-do list becomes tasks; a manual becomes a guide
  the family can ask about.
- **Bug reports from the chat**: `/bug` and `/idea`, or just "that's a bug...".

## Your day

- **One morning message**: a good morning and today's calendar, with buttons for today's
  tasks, held email, everything else and "just one thing". See
  [MORNING_MESSAGE.md](MORNING_MESSAGE.md).
- **The day card**: the same day drawn as a picture, with the weather, your calendar, time
  held for tasks and what's waiting. Pictures of the week, your tasks, the family's chores and
  routines are a message away too.
- **Calendars**: reads each person's Google calendars (privately, unless they share),
  creates and moves events after a yes, spots the same event twice, and blocks time for
  tasks.
- **When to leave**: drive times with live traffic (TomTom, or OpenStreetMap for free), a
  "start getting ready" heads-up, and stops on the way.
- **Weather**: a line in the morning only when the day's weather is worth knowing (rain,
  snow, a freeze, real heat, strong wind), with US warnings from the National Weather
  Service.
- **The wall**: a page for the family's wall frame (a Cozyla, or any tablet): the time, today's
  timeline for each person, everyone's to-dos, routines and chores, the week ahead, parcels
  and the shared lists. It dims at bedtime and shows tomorrow.
- **Parcels**: tracking numbers from shipping emails and carriers' alerts, checked with UPS
  and USPS, on the wall and in the morning.

## Tasks, chores and routines

- **Tasks** from chat, voice ("Hey Google, add a task..."), email or photos; urgent and
  important; split into steps; "remind me at 7" is a reminder, not a task.
- **Chores** that repeat on a schedule, anchored to the last time they were done, shared
  between people, and gently escalated when they slip. Themi keeps the wall's chore chart.
- **Routines** (morning, evening) kept in Themi and on the wall, with a check-in if steps are
  left.
- **Exercise plans**: either-day rounds, rest days, sunset-relative runs and distance plans.
- **Lists** on demand, with sub-items; "things to buy" sorted by store.
- **Seasonal maintenance**: the furnace filter, the smoke alarms, the gutters, on their own
  schedule.
- **Medicines**: reminders that always arrive, with safe wording.
- **Expense sheets**: business and takeout spending from receipts, calendars and chat, kept
  in Google Sheets, exported as CSV with an audit trail.

## Email

- **Triage** of each person's Gmail Primary inbox: urgent, needs a reply, a confirmation, a
  receipt, or noise. Notices come with **Open in Gmail**, **Not important**, **Mark read**
  and **Make it a task**.
- **Approvals**: a drafted reply, a confirmation to mark read, an event from an invitation or
  booking, all from one card per thread. Nothing happens without a yes unless a rule allows
  it.
- **Parcels** in shipping emails are followed until they arrive.
- **Expected emails**: Themi notices when a usual bill or statement doesn't arrive, or looks
  wrong.
- **The noise digest**: everything unimportant in one message, to archive in one go.
- **The email audit**: suggestions for senders that matter and ones that don't, as a short
  list instead of one question at a time.
- Forwarding, follow-ups on threads waiting for a reply, and receipts into expenses.

## Food: groceries, meals and cooking

- **One grocery list**, kept in step with OurGroceries and Google Keep (so "Hey Google, add
  milk" works), with a pantry that tracks what's running low.
- **The Safeway cart** filled from the list by a Chrome extension, remembering the products
  you pick.
- **Meal ideas** from the family cookbook, and a takeout rescue on nights that need one.
- **The family cookbook** read from a Google Doc. Recipes from a link, a web search or a
  photo; scaled; ingredients onto the grocery list; keepers saved to the cookbook.
- **The cook screen**: a full-screen kitchen companion on a phone or tablet: gather, prep,
  one step at a time with this step's amounts in cups and grams, timers on a rail, push-to-talk
  questions, look-ahead, swaps, music for the mood, and Themi the chameleon for company.
- **The oven**: the recipe's preheat, proof and timers sent to a GE Café range through
  SmartHQ, and off when you're done.

## The house

Each device reads its status and turns problems into a chore for whoever has more room, with
a nudge a little later. If the problem sorts itself out first, nothing is sent.

- **Washer and dryer** (LG ThinQ): "move the load" half an hour after the washer finishes; a
  rewash suggestion if it sat too long.
- **Dishwasher** (Home Connect): ticks the dishwasher routine when it starts, and notices
  when the household is falling behind.
- **Robot vacuum** (Roborock): stuck, full, empty or off its dock, named by room; sent back to
  its dock once it's sorted.
- **Pet feeders** (SmartLife / Tuya): food low or out, jams; "has the cat been fed?" and "feed
  Juneau".
- **Litter box** (CatGenie): errors, sani-solution, and a granule top-up every so many
  cleans.
- `/pause laundry` (or vacuum, feeders, litter, everything) holds the nudges for a while.

## Getting things done together

- **Partners**: "tell her I'll be late" passes a message on at a good moment; "what's on his
  plate?" and "she's overwhelmed" get honest answers and an offer to take something.
- **Shared tasks** stay with whoever didn't put them off; "either of you" chores go to
  whoever has more room.
- **Body doubling**: Themi keeps you company through a task: a quiet anchor, a sprint
  partner, or a guided step-through with a picture for each step and music that suits the
  task (built-in or your own Spotify).
- **Calls**: a short script for calling a company or vendor, and a nudge before they close.
- **Web search**: Themi can look things up and read a page, near home when it matters.

## Trust: what Themi does on its own

Every action that changes something (adding an event, archiving an email, ticking a chore)
goes through **trust tiers**. New kinds of action start as "ask first"; each person can let
Themi do more on its own as it earns it, on the website's "What Themi does alone" page.
Rules can be drafted from chat ("always archive the school newsletter"), checked, and
locked. Whatever Themi did on its own is always said in its reply.

## Privacy and your data

- Themi runs on **your own server**. Your email, calendar and chats stay there.
- Every token, key and password is **encrypted at rest** and kept out of the logs. Backups
  are encrypted too.
- Each person's calendar is **private by default**; they choose whether a partner sees
  details, a label or just "busy".
- Emails, web pages and other outside text are treated as data, never as instructions.
- AI calls go to the provider each person chooses, or a local model that never leaves the
  house.

## Not just for families

Themi starts from a **template**: `family` (everything above), `work` (one person's working
day: tasks, follow-ups, calendar and email, in Slack or Telegram), or `empty` (an AI provider
and nothing else, to build up from the Modules page). A second Themi can run beside the
family's on the same machine.
