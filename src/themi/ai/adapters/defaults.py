"""Default models and URLs per provider, without loading any provider's SDK.

The SDKs take seconds to import on a Raspberry Pi, so code that only needs these
names (settings pages, `themi feedback`) imports them from here. The adapter
modules re-export them.
"""

from __future__ import annotations

ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
ANTHROPIC_DEFAULT_EFFORT = "medium"

# gemini-3.8-flash allowed only 20 free requests a day; flash-lite has room for a household.
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"
GEMINI_DEFAULT_TRANSCRIPTION_MODEL = "gemini-3.5-flash-lite"
# P7b: gemini-embedding-2 told "lie down" from "oat milk" further apart than -001 did.
GEMINI_DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"

OLLAMA_URL = "http://localhost:11434/v1"
LM_STUDIO_URL = "http://localhost:1234/v1"
