"""Gantry hardware and configuration module."""

from .coordinates import Coordinates
from .errors import (
    CommandExecutionError,
    GantryLoaderError,
    LocationNotFound,
    MillConnectionError,
    StatusReturnError,
)
from .gantry import Gantry
from .gantry_config import (
    GantryConfig,
    GantryType,
    HomingStrategy,
    WorkingVolume,
)
from .loader import load_gantry_from_yaml, load_gantry_from_yaml_safe
from .machine_geometry import (
    FixedStructureBox,
    fixed_structures_for_gantry,
    fixed_structures_for_gantry_type,
)

__all__ = [
    "Gantry",
    "GantryConfig",
    "CommandExecutionError",
    "Coordinates",
    "GantryLoaderError",
    "GantryType",
    "FixedStructureBox",
    "HomingStrategy",
    "LocationNotFound",
    "MillConnectionError",
    "StatusReturnError",
    "WorkingVolume",
    "fixed_structures_for_gantry",
    "fixed_structures_for_gantry_type",
    "load_gantry_from_yaml",
    "load_gantry_from_yaml_safe",
]
