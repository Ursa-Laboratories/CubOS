"""Pydantic schema for the Duet/RepRapFirmware settings block.

Unlike ``grbl_settings`` — which declares runtime-writable controller
settings — Duet motion configuration lives in the board's version-controlled
``config.g``. This block only carries state CubOS itself must restore:
RepRapFirmware does not persist workplace (G54) offsets across reboots, so
the deck-origin calibration result is stored here and re-applied by
``Gantry.connect``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class WorkOffsetsYaml(BaseModel):
    """Calibrated G54 workplace offsets in machine-frame millimeters."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    z: float


class DuetSettingsYaml(BaseModel):
    """Duet-specific gantry settings."""

    model_config = ConfigDict(extra="forbid")

    work_offsets: Optional[WorkOffsetsYaml] = None
