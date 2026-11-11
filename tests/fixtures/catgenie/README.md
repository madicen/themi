# CatGenie payloads (CG1a)

Payloads in the shapes PetNovations' cloud sends, as the community client
[kclif9/catgenieapi](https://github.com/kclif9/catgenieapi) (`catgenie` 0.1.6) documents them
in its models and test fixtures (read 2026-11-04). `tests/fakes/catgenie.py` serves them.

- `device.json`: one entry of `GET device/device/v2`'s `thingList`: a CatGenie A.I.,
  connected, idle, with 39% sani-solution left and no errors.
- `device_whoosh.json`: a CatGenie Whoosh (`fwVersion` 100.4.14R), captured from the family's
  own box on 2026-11-11 (F41a, bug #197), with its ids, name and addresses replaced. Its
  `remainingSaniSolution` (477) is **cleans left**, as the app shows it, not a percent.
  The A.I. (`fwVersion` 8.x, `device.json`) reports a percent.
- `notification.json`: one entry of `GET notification/v1/push/user`'s `notifications`. Its
  `data` is JSON text; `type` 24 with an empty `errorType` is the package's one sample, and
  nothing says what 24 means.

None of these are captures from the family's own litter box, and the error codes the tests
use ("HEATER_FAULT", "DOME_OPEN") are stand-ins. Once CatGenie is linked, run
`themi catgenie capture --out tests/fixtures/catgenie/captured` (ids, names and numbers are
left out), ideally while the box shows each state it can: cleaning, the cartridge low or
out, the dome off, any error. Then each real code gets its words in
`themi.connectors.catgenie.events.CODES` (and notification types in `ALERT_TYPES`), with a
test.
