"""Shared instrument YAML schemas for machine configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


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

    Common fields are declared explicitly. Driver-specific fields
    (e.g. serial_number, dll_path) pass through via extra="allow".

    Z semantics
    -----------
    Instruments declare only their physical mounting (``offset_x``,
    ``offset_y``, ``depth``). Labware-relative motion heights live on the
    protocol commands that engage with labware:

    * ``measurement_height`` — first-class arg to ``measure`` and ``scan``.
    * ``interwell_scan_height`` — first-class arg to ``scan``.

    Inter-labware travel uses the gantry-level ``safe_z`` (absolute).

    Stale ``measurement_height``/``interwell_scan_height`` keys are
    rejected explicitly — the ``extra="allow"`` policy would otherwise
    silently swallow them for drivers that accept ``**kwargs``.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    vendor: str
    offset_x: float = 0.0
    offset_y: float = 0.0
    depth: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _reject_relocated_height_fields(cls, data):
        if isinstance(data, dict):
            for key, hint in _RELOCATED_HEIGHT_FIELDS.items():
                if key in data:
                    raise ValueError(hint)
        return data
