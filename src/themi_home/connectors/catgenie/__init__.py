"""CatGenie: the litter box, through the CatGenie app's cloud (PetNovations) (CG1a)."""

from themi_home.connectors.catgenie.client import (
    BadCode,
    CatGenieAccount,
    CatGenieClient,
    CatGenieConfig,
    CatGenieError,
    SignInLost,
)
from themi_home.connectors.catgenie.events import (
    ALERT,
    CLEANS,
    ERROR,
    GRANULES,
    LOW,
    OUT,
    SOLUTION,
    LitterBoxEvent,
    LitterBoxReading,
)
from themi_home.connectors.catgenie.watch import (
    CatGenieWatcher,
    LitterBoxListener,
    ReadingListener,
)

__all__ = [
    "ALERT",
    "CLEANS",
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
