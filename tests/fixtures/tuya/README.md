# Tuya feeder payloads (32)

Payloads in the shapes Tuya's cloud API sends: the `result` of
`GET /v1.0/devices/{id}/specifications` (`*_spec`) and `/v1.0/devices/{id}/status` (the
rest). `tests/fakes/tuya.py` serves them.

- `standard_*`: Tuya's standard pet feeder (category `cwwsq`), from its published status
  set (developer.tuya.com, read 2026-11-04).
- `fault_*`: a feeder with a model-specific `fault` bitmap and no food level, the shape many
  models use. The labels are typical ones, not a particular model's.

- `captured/drfffce9jdtayqty.json`: the family's own feeders (Juneau, Merlin, Mimikos, one
  model), captured with `themi tuya capture` on 2026-11-10 (F39a). Its writable `manual_feed`
  (1 to 12) is how Themi feeds now; it reports no food level or fault.

Apart from `captured/`, none of these are captures from the family's own feeders. Once Tuya is linked, run
`themi tuya capture --out tests/fixtures/tuya/captured` (ids, keys and names are left
out), and add a test for each model; a model the rules misread gets its own line in
`themi.connectors.tuya.events.MODELS`.
