"""CR7a: a member's settings that belong to one module.

A module declares a model of its preferences, with defaults and checks:

    class BreaksPreferences(Preferences):
        module: ClassVar[str] = "breaks"
        break_extend_minutes: int = 15

        @field_validator("break_extend_minutes")
        @classmethod
        def _extend(cls, value: int) -> int: ...

and reads and saves them through the account store:

    prefs = store.preferences(member.id, BreaksPreferences)
    store.save_preferences(actor, member.id, BreaksPreferences, break_extend_minutes=25)

A preference the member never set is the model's default. A check's ValueError comes back
as InvalidValue with its words, as the member settings' checks do.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class Preferences(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: ClassVar[str] = ""
