"""Public gantry error types.

Setup scripts and higher-level runtime code import hardware/control errors
from this module instead of reaching into ``gantry_driver``. The driver
exceptions are re-exported here so the ``gantry_driver`` package stays an
internal implementation detail behind the ``Gantry`` boundary.
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
