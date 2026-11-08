"""CR21c: the wall's settings, for both its modules."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from themi.core.connector_settings import _together
from themi.modules.settings import ModuleSettings, env_field
from themi.storage.secrets import Secret
from themi_cozyla.connector.client import CozylaConfig


class CozylaSettings(ModuleSettings):
    """The Cozyla wall (unofficial API), for both wall modules."""

    email: str = env_field("COZYLA_EMAIL", "", ask="Cozyla account email")
    password: Secret | None = env_field("COZYLA_PASSWORD", secret=True, ask="Cozyla password")
    todo_list: str = env_field(
        "COZYLA_TODO_LIST", "", ask="The wall's to-do list to keep in step (blank: none)"
    )
    device_sn: str = env_field("COZYLA_DEVICE_SN", "themi")
    chores: bool = env_field(
        "COZYLA_CHORES", False, ask="Keep the wall's chore chart in step? (yes or no)"
    )

    @model_validator(mode="after")
    def _pair(self) -> Self:
        _together("COZYLA_EMAIL", "COZYLA_PASSWORD", self.email, self.password)
        return self

    def config(self) -> CozylaConfig | None:
        if not self.email or self.password is None:
            return None
        return CozylaConfig(
            self.email, self.password, self.todo_list, self.device_sn, chores=self.chores
        )
