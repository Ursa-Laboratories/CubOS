from __future__ import annotations

import math
from typing import Any

from .errors import MillConnectionError


def round_mm(value: float) -> float:
    """Round a millimeter value to CubOS calibration precision."""
    return round(float(value), 3)


def validate_homing_pull_off_mm(value: Any) -> float:
    """Validate and normalize GRBL $27 homing pull-off."""
    try:
        pull_off = float(value)
    except (TypeError, ValueError) as exc:
        raise MillConnectionError(
            "Cannot finalize deck-origin calibration because GRBL $27 "
            f"homing pull-off is not numeric: {value!r}."
        ) from exc
    if not math.isfinite(pull_off) or pull_off < 0:
        raise MillConnectionError(
            "Cannot finalize deck-origin calibration because GRBL $27 "
            f"homing pull-off must be finite and non-negative; got {value!r}."
        )
    return round_mm(pull_off)


def validate_status_report(value: Any) -> float:
    """Validate and normalize GRBL $10 status-report mode."""
    try:
        status_report = float(value)
    except (TypeError, ValueError) as exc:
        raise MillConnectionError(
            "Cannot configure calibration GRBL settings because $10 "
            f"status report is not numeric: {value!r}."
        ) from exc
    if not math.isfinite(status_report):
        raise MillConnectionError(
            "Cannot configure calibration GRBL settings because $10 "
            f"status report must be finite; got {value!r}."
        )
    return status_report
