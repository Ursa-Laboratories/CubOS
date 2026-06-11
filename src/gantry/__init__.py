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
from .instrument_loader import (
    build_instrumented_gantry,
    load_instrumented_gantry_from_config,
    load_instrumented_gantry_from_yaml,
    load_instrumented_gantry_from_yaml_safe,
)
from .instrument_mount import InstrumentedGantry
from .loader import load_gantry_from_yaml, load_gantry_from_yaml_safe
from .limit_recovery import (
    LimitRecoveryResult,
    looks_like_limit_alarm,
    recover_from_limit_alarm,
)
from .machine_geometry import (
    FixedStructureBox,
    fixed_structures_for_gantry,
    fixed_structures_for_gantry_type,
)

__all__ = [
    "Gantry",
    "GantryConfig",
    "InstrumentedGantry",
    "CommandExecutionError",
    "Coordinates",
    "GantryLoaderError",
    "GantryType",
    "FixedStructureBox",
    "HomingStrategy",
    "LocationNotFound",
    "MillConnectionError",
    "LimitRecoveryResult",
    "StatusReturnError",
    "WorkingVolume",
    "build_instrumented_gantry",
    "fixed_structures_for_gantry",
    "fixed_structures_for_gantry_type",
    "looks_like_limit_alarm",
    "load_gantry_from_yaml",
    "load_gantry_from_yaml_safe",
    "load_instrumented_gantry_from_config",
    "load_instrumented_gantry_from_yaml",
    "load_instrumented_gantry_from_yaml_safe",
    "recover_from_limit_alarm",
]
