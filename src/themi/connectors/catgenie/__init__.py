"""CatGenie: the litter box, through the CatGenie app's cloud (PetNovations) (CG1a)."""

from themi.connectors.catgenie.client import (
    BadCode,
    CatGenieAccount,
    CatGenieClient,
    CatGenieConfig,
    CatGenieError,
    SignInLost,
)
from themi.connectors.catgenie.events import (
    ALERT,
    ERROR,
    GRANULES,
    LOW,
    OUT,
    SOLUTION,
    LitterBoxEvent,
    LitterBoxReading,
)
from themi.connectors.catgenie.watch import (
    CatGenieWatcher,
    LitterBoxListener,
    ReadingListener,
)

__all__ = [
    "ALERT",
    "ERROR",
    "GRANULES",
    "LOW",
    "OUT",
    "SOLUTION",
    "BadCode",
    "CatGenieAccount",
    "CatGenieClient",
    "CatGenieConfig",
    "CatGenieError",
    "CatGenieWatcher",
    "LitterBoxEvent",
    "LitterBoxListener",
    "LitterBoxReading",
    "ReadingListener",
    "SignInLost",
]
