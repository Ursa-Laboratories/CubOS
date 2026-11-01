"""Shared schema and validation for pipette travel clearance."""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field

PipetteTravelClearance = Annotated[
    float | None,
    Field(
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description=(
            "Requested pipette travel clearance in mm above the registered plate "
            "top; the planner may raise it or use the travel ceiling. A null "
            "value keeps full ceiling retraction."
        ),
    ),
]


def validate_pipette_travel_clearance(value: object) -> float | None:
    """Reject invalid clearance values at direct Python command boundaries."""
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise ValueError(
            "travel_clearance must be null or a finite non-negative number in mm"
        )
    return float(value)
