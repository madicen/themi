"""CR19: what Themi can do with what it's sent, or make, as modules of the "capability" kind.

- `voice_notes`: voice notes are transcribed and treated like text. Without it, a voice
  note gets a word that typing works.
- `pictures`: pictures sent in chat are looked at (a member's backend must take images).
  Without it, a picture gets a word that describing it in text works, and reading a recipe
  from a picture isn't offered.
- `image_generation`: Themi makes pictures (guided steps' pictures), with a picture model
  set up on the AI page under its own key. Without it, step pictures and the tools that
  make or send them aren't offered.
"""

from __future__ import annotations

from themi.core.capabilities import IMAGE_GENERATION, PICTURES, VOICE_NOTES
from themi.modules import Module, ModuleContext


class CapabilityModule(Module):
    kind = "capability"

    def install(self, ctx: ModuleContext) -> None:
        ctx.capability(self.name)


class VoiceNotesModule(CapabilityModule):
    """Voice notes, transcribed."""

    name = VOICE_NOTES


class PicturesModule(CapabilityModule):
    """Pictures sent in chat, looked at."""

    name = PICTURES


class ImageGenerationModule(CapabilityModule):
    """Pictures made by a picture model (its own key, on the AI page)."""

    name = IMAGE_GENERATION
