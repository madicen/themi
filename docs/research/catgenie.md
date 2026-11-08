# CatGenie: how Themi can read the litter box

As of 2026-11-08.

The family has a CatGenie A.I. (PetNovations), a self-washing litter box with washable
granules and a sani-solution cartridge. Themi wants its errors and supplies as chores.

## Options

| Route | What it gives | State |
|---|---|---|
| Official API | Nothing: none exists | No public API, developer programme or third-party integration (Alexa, IFTTT) is mentioned on [the app page](https://catgenie.com/pages/catgenie-app) |
| Community client, `catgenie` on PyPI | Devices, status, notifications, start/stop cleaning | Unofficial, reverse-engineered; what Themi follows (CG1a) |
| Home Assistant integrations | The same data, via the same client | Not in HA core; custom integrations only |
| Email or push from the app | "Needs attention" and low-cartridge alerts | Push only, as far as the app page says; email alerts not confirmed |
| Watching the box locally (power, Wi-Fi) | Whether it ran | Crude; not looked at further |

## The community client

- The repository was renamed. `github.com/kclif9/catgenieapi` (the link in CG1a's notes and
  in `client.py`) now returns 404. The code lives at
  [kclif9/catgenie-api](https://github.com/kclif9/catgenie-api) (MIT, last push 2026-05-06).
  Its README still links the old name for `git clone`.
- [`catgenie` on PyPI](https://pypi.org/project/catgenie/): 0.1.6, uploaded 2026-05-06, MIT,
  Python >= 3.13, depends on `curl-cffi`, `pycryptodome` and `pydantic`. Read from PyPI's JSON
  API; the HTML page didn't load. No release since May.
- Its README says: a reverse-engineered async client for `iot.petnovations.com`
  (CloudFront in front of AWS API Gateway); phone plus SMS code sign-in "using the same OTP
  mechanism as the official app"; access tokens about 30 minutes, refresh token about 10
  years; start/stop cleaning; sani-solution level; notification history and settings.
- It credits [Rukongai/CatDjinni](https://github.com/Rukongai/CatDjinni) for the signing
  research. Two older HA integrations
  ([PrimeAutomation/petnovations](https://github.com/PrimeAutomation/petnovations), now
  archived, and [appkins/hass-catgenie](https://github.com/appkins/hass-catgenie)) needed a
  refresh token captured by hand from the app's traffic.
- Two HA integrations build on it:
  [kclif9/hasscatgenie](https://github.com/kclif9/hasscatgenie) (says it is a test version of
  one being submitted to HA core; `homeassistant/components/catgenie` doesn't exist in core
  today) and [PrimeAutomation/HA-Catgenie](https://github.com/PrimeAutomation/HA-Catgenie)
  (active, last push 2026-11-03).

## The app's traffic

- The README: "PetNovations' edge silently discards requests from Python's standard SSL
  stack, returning 200 OK with an empty body". It uses curl_cffi to look like Chrome on
  Android. Themi does the same (`chrome131_android`).
- Sign-in is a phone number and a code sent by text. The phone number is AES-CBC encrypted
  with a key taken from the app. The app also sends HMAC signatures; per the package the
  server doesn't check them, so Themi doesn't send them.
- The edge's TLS filter and the static key are both things PetNovations can change in an app
  update without notice.

## What the API gives, and doesn't

From CG1a's reading of the package (`GET device/device/v2`, `GET notification/v1/push/user`)
and the HA-Catgenie sensor list:

- Gives: online, cleaning now and progress, last clean, operation error, `activeErrors`,
  sani-solution left (%) and cartridge capacity, lifetime cycle count, settings (mode,
  schedule, sensitivity, panel lock), `dome`, `fanShutter`, `lowHeater` flags (HA-Catgenie
  calls the last two "raw diagnostics ... their meaning is undocumented"), and the app's push
  history with a numeric `type` and `errorType`.
- Doesn't give: granule (litter) level. Nothing in the package, the HA integrations or the
  app page reads one. The app page only describes a "reminder tool" for the Whoosh model.
- Unknown: what the error and notification codes mean. Nobody publishes a table.

## Risks

- Unofficial: no terms allow it, and no support if it stops.
- Can break silently: a changed TLS filter returns empty 200s, not errors. Themi treats an
  empty or non-JSON answer as a failure, never as "no problems".
- Sign-in by text code needs a person at the phone to relink.
- The package hasn't had a release since May 2026; the HA integrations are where fixes would
  show up first.
- Error codes are guessed until the family's captures come in.

## What Themi built

- CG1a (2026-11-04): our own read-only client over curl_cffi (`src/themi_home/connectors/catgenie/`),
  credited to the package. Linking by phone and text code on the Accounts page, refresh token
  encrypted, phone number not kept. A watcher every 10 minutes, raw captures kept, and
  `themi catgenie capture` for the family to share examples.
- CG1b (2026-11-04): errors, alerts, low or no sani-solution, and a granule top-up every N
  cleans (from the lifetime count, a household setting) become effort-1 chores. The box
  showing it's sorted closes them.
- Still to do: the family's captures, then the error and alert code tables.

Viable path: yes, built as CG1a/CG1b.

## Fallback if it breaks

A proposal only. If PetNovations closes the door, Themi keeps the last lifetime cycle count it
saw and the box's usual cleans per day. From those it estimates when the cartridge runs out
(cartridge capacity in cycles) and when the granules are due (the CG1b N). Near each estimate
it asks one person a quick check-in task ("Is the CatGenie's cartridge light on?"), and the
answer resets the estimate. The admins are told once that it is estimating, not reading.

## Proposed follow-up prompts

- Update the repository link in `client.py` and CG1a's notes to `kclif9/catgenie-api`.
- CG1c: the error and alert code tables from the family's captures, with tests.
- CG1d (only if it breaks): estimate-and-check-in fallback as above.
