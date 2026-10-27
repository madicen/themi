"""Themi: a household assistant for one family."""

import os

# A released image says which tag it was built from (the release workflow sets this).
__version__ = os.environ.get("THEMI_BUILD_VERSION") or "0.1.0"
