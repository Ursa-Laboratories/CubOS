"""Shared GRBL settings schema and normalization helpers."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict


class GrblSettingsYaml(BaseModel):
    """Expected GRBL controller settings.

    These mirror GRBL ``$`` settings that affect motion behavior and safety.
    All fields are optional; only specified values are checked or emitted.
    """

    model_config = ConfigDict(extra="forbid")

    dir_invert_mask: Optional[int] = None
    status_report: Optional[int] = None
    soft_limits: Optional[bool] = None
    hard_limits: Optional[bool] = None
    homing_enable: Optional[bool] = None
    homing_dir_mask: Optional[int] = None
    homing_pull_off: Optional[float] = None
    steps_per_mm_x: Optional[float] = None
    steps_per_mm_y: Optional[float] = None
    steps_per_mm_z: Optional[float] = None
    max_rate_x: Optional[float] = None
    max_rate_y: Optional[float] = None
    max_rate_z: Optional[float] = None
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None
    max_travel_x: Optional[float] = None
    max_travel_y: Optional[float] = None
    max_travel_z: Optional[float] = None


GRBL_FIELD_TO_SETTING = {
    "dir_invert_mask": "$3",
    "status_report": "$10",
    "soft_limits": "$20",
    "hard_limits": "$21",
    "homing_enable": "$22",
    "homing_dir_mask": "$23",
    "homing_pull_off": "$27",
    "steps_per_mm_x": "$100",
    "steps_per_mm_y": "$101",
    "steps_per_mm_z": "$102",
    "max_rate_x": "$110",
    "max_rate_y": "$111",
    "max_rate_z": "$112",
    "accel_x": "$120",
    "accel_y": "$121",
    "accel_z": "$122",
    "max_travel_x": "$130",
    "max_travel_y": "$131",
    "max_travel_z": "$132",
}


def coerce_setting_value(value: Any) -> float:
    """Normalize YAML/user values to numeric GRBL setting values."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def normalize_expected_grbl_settings(
    settings: GrblSettingsYaml | Mapping[str, Any] | None,
) -> dict[str, float] | None:
    """Return expected GRBL settings keyed by ``$`` code."""
    if settings is None:
        return None
    raw = (
        settings.model_dump(exclude_none=True)
        if isinstance(settings, GrblSettingsYaml)
        else dict(settings)
    )
    normalized: dict[str, float] = {}
    for field_name, grbl_code in GRBL_FIELD_TO_SETTING.items():
        if field_name in raw and raw[field_name] is not None:
            normalized[grbl_code] = coerce_setting_value(raw[field_name])
    return normalized or None


def format_setting_value(value: Any) -> str:
    """Format a GRBL setting value for ``$N=value`` commands."""
    numeric = coerce_setting_value(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.6f}".rstrip("0").rstrip(".")
