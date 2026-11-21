# Tracking number patterns

`ups.json`, `usps.json`, `fedex.json`, `amazon.json` and `LICENSE` are copied unchanged from
Jeff Keen's [tracking_number_data](https://github.com/jkeen/tracking_number_data), release
v2.0.0 (commit fec2d02d2d2d410fdccc077edf155885649a9b6c), under the MIT licence in `LICENSE`.

Vetted for PT1 on 2026-11-21 (the Themi Package Tracking Plan):

- Licence: MIT, which allows copying with the notice kept (it's here).
- Contents: each file holds the patterns, check digit rules, test numbers, service-type
  names, descriptions and a `tracking_url` per kind. Themi reads only the patterns, check
  digits and test numbers. It never uses `tracking_url`: Themi never follows or builds a
  tracking link.
- Matching: `tests/unit/test_tracking_numbers.py` checks every valid and invalid test
  number in these files, and order numbers, phone numbers and dates that must not match.

To update: copy the four files from a newer tagged release, change the release and commit
above, and run that test file.
