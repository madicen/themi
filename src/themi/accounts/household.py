"""CR7c: the household's settings that belong to one module (the takeout budget is
spending's, the staples are the pantry's). Kept in `household_settings`, one row per
setting, the value as JSON; an admin changes them. The family's own fields (its name,
timezone, who does which kind of task) stay on `Family`.

    class SpendingSettings(HouseholdSettings):
        module: ClassVar[str] = "spending"
        takeout_budget_cents: int = 0

    store.household(SpendingSettings).takeout_budget_cents
    store.save_household(admin, SpendingSettings, takeout_budget_cents=300_00)
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class HouseholdSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: ClassVar[str] = ""
