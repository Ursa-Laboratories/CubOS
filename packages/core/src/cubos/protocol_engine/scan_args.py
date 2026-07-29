"""Scan argument normalization.

The scan command's required heights (``measurement_height``,
``interwell_scan_height``) and the optional ``indentation_limit_height``
are first-class function parameters and are validated by the command
itself, not here. This module only handles ``method_kwargs``
reconciliation: rejecting legacy field names and re-stating which
top-level fields carry the same meaning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class NormalizedScanArguments:
    """Runtime scan arguments after compatibility checks."""

    method_kwargs: dict[str, Any]


_LEGACY_KWARG_HINTS = {
    "entry_travel_height": (
        "`entry_travel_height` is no longer supported. Inter-labware/entry "
        "travel uses the gantry's `safe_z` (absolute deck-frame Z)."
    ),
    "interwell_travel_height": (
        "`interwell_travel_height` is no longer supported. Use "
        "`interwell_scan_height` (labware-relative offset)."
    ),
    "safe_approach_height": (
        "`safe_approach_height` was renamed to `interwell_scan_height` "
        "(labware-relative offset above the well surface for between-wells "
        "XY travel)."
    ),
    "z_limit": (
        "`z_limit` is no longer supported. Use `indentation_limit_height`."
    ),
    "indentation_limit": (
        "`indentation_limit` was renamed to `indentation_limit_height` "
        "and its meaning changed: it is now a *signed* labware-relative "
        "offset (mm above the well surface; negative = below), not a "
        "sign-agnostic descent magnitude. To indent 5 mm into a well, use "
        "`indentation_limit_height: -5.0`."
    ),
    "measurement_height": (
        "`measurement_height` does not belong in `method_kwargs` — the "
        "engine resolves it from the top-level `measurement_height` field "
        "and would silently overwrite this value. Move it to the top level."
    ),
    "interwell_scan_height": (
        "`interwell_scan_height` does not belong in `method_kwargs`. Move "
        "it to the top level of the scan command."
    ),
    "indentation_limit_height": (
        "`indentation_limit_height` does not belong in `method_kwargs`. "
        "Move it to the top level of the scan command."
    ),
}


def surface_detection_enabled(
    method_kwargs: Mapping[str, Any] | None,
) -> bool:
    """True when ``method_kwargs`` opts into ASMI surface detection.

    With ``detect_surface`` enabled, ``indentation_limit_height`` is
    anchored to the sensor-detected sample surface instead of the
    calibrated well surface, so commands and validators must not compare
    it against ``measurement_height`` (different frames) and instead
    require it to be at or below zero.
    """
    return bool((method_kwargs or {}).get("detect_surface"))


def normalize_scan_arguments(
    *,
    method_kwargs: Mapping[str, Any] | None = None,
) -> NormalizedScanArguments:
    """Validate and normalize the scan command's ``method_kwargs``.

    Raises:
        ValueError: When legacy or first-class fields appear inside
            ``method_kwargs``.
    """
    kwargs = dict(method_kwargs or {})

    for legacy_key, message in _LEGACY_KWARG_HINTS.items():
        if legacy_key in kwargs:
            raise ValueError(message)

    return NormalizedScanArguments(method_kwargs=kwargs)
