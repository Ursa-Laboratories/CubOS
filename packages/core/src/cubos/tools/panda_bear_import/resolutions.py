"""Load and validate the PANDA-BEAR import resolutions YAML.

Resolutions encode only row-selection facts verified against the production
snapshot: which duplicate/corrupt vial rows to drop, which declared shapes to
distrust in favor of actual per-row data, which tip rack to skip entirely,
and the one missing physical constant (tip length). Positional/geometric
issues (out-of-envelope coordinates, well-grid pitch residuals, vial content
sum drift) are reported as warnings and never require a resolution -- see
``build.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from cubos.yaml_utils import load_yaml_file

_ALLOWED_KEYS = {
    "exclude_vial_ids",
    "tiprack_shape_overrides",
    "exclude_tiprack_ids",
    "tip_length_mm",
    "wellplate_height_overrides",
}


class ResolutionsError(ValueError):
    """Raised for a malformed resolutions YAML."""


@dataclass(frozen=True)
class Resolutions:
    exclude_vial_ids: frozenset[int] = frozenset()
    tiprack_shape_overrides: Mapping[int, tuple[int, int]] = field(default_factory=dict)
    exclude_tiprack_ids: frozenset[int] = frozenset()
    tip_length_mm: float | None = None
    wellplate_height_overrides: Mapping[int, float] = field(default_factory=dict)


def empty_resolutions() -> Resolutions:
    """Return a Resolutions with nothing pre-resolved (for conflict-detection tests)."""
    return Resolutions()


def load_resolutions(path: str | Path) -> Resolutions:
    """Load and strictly validate a resolutions YAML file."""
    raw = load_yaml_file(path)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ResolutionsError(f"Resolutions YAML at {path} must be a mapping.")
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise ResolutionsError(
            f"Resolutions YAML at {path} has unknown keys: {sorted(unknown)}. "
            f"Allowed keys: {sorted(_ALLOWED_KEYS)}."
        )

    exclude_vial_ids = frozenset(_int_list(raw.get("exclude_vial_ids", []), "exclude_vial_ids"))
    exclude_tiprack_ids = frozenset(
        _int_list(raw.get("exclude_tiprack_ids", []), "exclude_tiprack_ids")
    )

    tiprack_shape_overrides: dict[int, tuple[int, int]] = {}
    for key, value in (raw.get("tiprack_shape_overrides") or {}).items():
        rack_id = _as_int(key, "tiprack_shape_overrides key")
        if not isinstance(value, dict) or set(value) != {"rows", "columns"}:
            raise ResolutionsError(
                "tiprack_shape_overrides entries must set exactly `rows` and `columns`, "
                f"got {value!r} for rack {rack_id}."
            )
        tiprack_shape_overrides[rack_id] = (
            _as_int(value["rows"], "tiprack_shape_overrides.rows"),
            _as_int(value["columns"], "tiprack_shape_overrides.columns"),
        )

    wellplate_height_overrides: dict[int, float] = {}
    for key, value in (raw.get("wellplate_height_overrides") or {}).items():
        plate_id = _as_int(key, "wellplate_height_overrides key")
        wellplate_height_overrides[plate_id] = float(value)

    tip_length_mm = raw.get("tip_length_mm")
    if tip_length_mm is not None:
        if isinstance(tip_length_mm, bool) or not isinstance(tip_length_mm, (int, float)):
            raise ResolutionsError("tip_length_mm must be a positive number.")
        tip_length_mm = float(tip_length_mm)
        if tip_length_mm <= 0:
            raise ResolutionsError("tip_length_mm must be positive.")

    return Resolutions(
        exclude_vial_ids=exclude_vial_ids,
        tiprack_shape_overrides=tiprack_shape_overrides,
        exclude_tiprack_ids=exclude_tiprack_ids,
        tip_length_mm=tip_length_mm,
        wellplate_height_overrides=wellplate_height_overrides,
    )


def _int_list(value, label: str) -> list[int]:
    if not isinstance(value, list):
        raise ResolutionsError(f"{label} must be a list of integers, got {value!r}.")
    return [_as_int(item, label) for item in value]


def _as_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResolutionsError(f"{label} must be an integer, got {value!r}.")
    return value
