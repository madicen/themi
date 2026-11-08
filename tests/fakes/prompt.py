"""CR8a: the family's system prompt, as composed from the template and every module.

It's the golden file (`make golden` writes it from the full family app), so tests that
read what the model is told about something use the same text the app sends.
"""

from __future__ import annotations

from pathlib import Path

FAMILY_SYSTEM = (Path(__file__).resolve().parents[1] / "golden" / "system_prompt.txt").read_text()
