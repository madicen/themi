"""PT4: asking the carriers about a parcel (the Themi Package Tracking Plan, Part 3).

    tracking = await UpsClient(client_id, secret).track("1Z...")

One client per carrier behind `Carrier`, plain HTTP over `httpx`; tests hand in a
transport (`tests/fakes/carriers.py`). Only the tracking number is sent. What comes back is
parsed into fields by code; its free text is cut short and shown as plain text.
"""

from themi.connectors.carriers.base import (
    STATUSES,
    Carrier,
    CarrierError,
    NotFound,
    Tracking,
)
from themi.connectors.carriers.ups import UpsClient
from themi.connectors.carriers.usps import UspsClient

__all__ = [
    "STATUSES",
    "Carrier",
    "CarrierError",
    "NotFound",
    "Tracking",
    "UpsClient",
    "UspsClient",
]
