"""Shared instrument YAML schemas for machine configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, FiniteFloat, model_validator


_RELOCATED_HEIGHT_FIELDS = {
    "measurement_height": (
        "`measurement_height` is no longer an instrument-config field — "
        "it is a first-class argument on the protocol `scan` and `measure` "
        "commands. Move it from `instruments.<name>.measurement_height` "
        "in the gantry YAML to the protocol step."
    ),
    "interwell_scan_height": (
        "`interwell_scan_height` is no longer an instrument-config field — "
        "it is a first-class argument on the protocol `scan` command. "
        "Move it from `instruments.<name>.interwell_scan_height` in the "
        "gantry YAML to the protocol step."
    ),
}


class InstrumentYamlEntry(BaseModel):
    """Schema for one gantry-mounted instrument.

    Driver-specific fields pass through via ``extra="allow"``. Explicitly
    reject protocol height fields so drivers cannot silently ignore them.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    vendor: str
    offset_x: FiniteFloat = 0.0
    offset_y: FiniteFloat = 0.0
    depth: FiniteFloat = 0.0

    @model_validator(mode="before")
    @classmethod
    def _reject_relocated_height_fields(cls, data):
        if isinstance(data, dict):
            for key, hint in _RELOCATED_HEIGHT_FIELDS.items():
                if key in data:
                    raise ValueError(hint)
        return data
