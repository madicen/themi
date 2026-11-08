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

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from themi.accounts.models import Member


class Preferences(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: ClassVar[str] = ""

    @classmethod
    def on_form(cls, services: Any, member: Member) -> set[str] | None:
        """The fields the settings page shows this member (None: all of them). One left off
        isn't saved from the form: a checkbox that wasn't there isn't unticked."""
        return None
