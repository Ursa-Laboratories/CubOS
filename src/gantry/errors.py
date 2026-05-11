"""Public gantry error types.

Setup scripts and higher-level runtime code should import hardware/control
errors from this module, not from the low-level ``gantry_driver`` package.
The names are aliases for now so existing exception behavior stays stable
while the driver boundary is cleaned up.
"""

from .gantry_driver.exceptions import (
    CNCMillException,
    CommandExecutionError,
    LocationNotFound,
    MillConnectionError,
    StatusReturnError,
)


class GantryLoaderError(Exception):
    """Human-friendly gantry loader error intended for CLI output."""


__all__ = [
    "CNCMillException",
    "CommandExecutionError",
    "GantryLoaderError",
    "LocationNotFound",
    "MillConnectionError",
    "StatusReturnError",
]
