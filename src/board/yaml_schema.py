"""Strict Pydantic schemas for legacy board YAML."""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict

from gantry.grbl_settings import GrblSettingsYaml
from instruments.yaml_schema import InstrumentYamlEntry


class BoardYamlSchema(BaseModel):
    """Root legacy board YAML schema.

    New machine configs should store mounted instruments and controller
    expectations in gantry YAML. This schema remains for legacy callers and
    focused board-loader tests.
    """

    model_config = ConfigDict(extra="forbid")

    grbl_settings: Optional[GrblSettingsYaml] = None
    instruments: Dict[str, InstrumentYamlEntry]
