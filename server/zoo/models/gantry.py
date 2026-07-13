"""API response shapes for gantry endpoints. The YAML schema itself comes
from CubOS (gantry.yaml_schema.GantryYamlSchema) — Zoo must not duplicate it."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class GantryResponse(BaseModel):
    filename: str
    config: Dict[str, Any]


class GantryPosition(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    work_x: Optional[float] = None
    work_y: Optional[float] = None
    work_z: Optional[float] = None
    status: str = "Unknown"
    connected: bool = False
    calibration_active: bool = False
    calibration_warning: Optional[str] = None
    move_error: Optional[str] = None
