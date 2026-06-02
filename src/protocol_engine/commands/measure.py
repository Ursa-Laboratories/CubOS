"""Protocol command: measure with an instrument at a deck position."""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from ..errors import ProtocolExecutionError
from ..registry import protocol_command
from ..scan_args import normalize_scan_arguments
from ._dispatch import inject_runtime_args
from ._movement import engage_at_labware

if TYPE_CHECKING:
    from ..protocol import ProtocolContext


@protocol_command("measure")
def measure(
    context: ProtocolContext,
    instrument: str,
    position: str,
    measurement_height: float,
    method: str = "measure",
    indentation_limit_height: float | None = None,
    method_kwargs: Dict[str, Any] = {},
) -> Any:
    """Measure at a deck position using *instrument*.

    Motion:
      1. Travel at the gantry's ``safe_z`` (absolute) to above the target.
      2. Descend straight down to ``well.z + measurement_height``.
      3. Call ``instrument.method(**method_kwargs)``.

    ``measurement_height`` is a required first-class argument: a
    labware-relative offset (mm above the well/labware calibrated surface Z;
    negative = below).

    ``indentation_limit_height`` is optional and only meaningful for
    closed-loop methods that declare it (e.g. ``ASMI.indentation``).
    Same semantics as on ``scan``: a signed labware-relative offset for
    the deepest descent plane; must be at or below ``measurement_height``.
    Lets ``measure`` drive a single-well indentation without iterating
    a plate.
    """
    if instrument not in context.gantry.instruments:
        raise ProtocolExecutionError(
            f"Unknown instrument '{instrument}'. "
            f"Available: {', '.join(sorted(context.gantry.instruments.keys()))}"
        )
    instr = context.gantry.instruments[instrument]

    if not hasattr(instr, method):
        raise ProtocolExecutionError(
            f"Instrument '{instrument}' has no method '{method}'."
        )

    # Reuse scan's legacy / first-class kwarg rejection so a user porting
    # an old config that put ``indentation_limit`` / ``z_limit`` /
    # ``safe_approach_height`` / ``measurement_height`` inside
    # ``method_kwargs`` gets the same rename hint here as on ``scan``,
    # rather than a generic Python TypeError or a silent overwrite.
    try:
        normalized = normalize_scan_arguments(method_kwargs=method_kwargs)
    except ValueError as exc:
        raise ProtocolExecutionError(str(exc)) from exc

    try:
        well_z, action_z = engage_at_labware(
            context, instrument, position,
            measurement_height=measurement_height,
            command_label="measure",
        )
    except ValueError as exc:
        raise ProtocolExecutionError(str(exc)) from exc

    context.logger.info(
        "measure: %s.%s(%s) at %s — action_z=%.3f",
        instrument, method, method_kwargs, position, action_z,
    )

    # Forward the labware-surface reference Z plus the user's labware-relative
    # offset so closed-loop instrument methods can resolve their own action /
    # target Z values. Open-loop methods that don't declare these parameters
    # receive only the YAML-supplied ``method_kwargs``.
    if (
        indentation_limit_height is not None
        and indentation_limit_height > measurement_height
    ):
        raise ProtocolExecutionError(
            f"measure: indentation_limit_height ({indentation_limit_height}) "
            f"is above measurement_height ({measurement_height}). The "
            "deepest descent plane must be at or below the action plane "
            "in +Z-up."
        )

    callable_method = getattr(instr, method)
    kwargs = inject_runtime_args(
        callable_method, normalized.method_kwargs, context,
        well_z=well_z,
        measurement_height=measurement_height,
        indentation_limit_height=indentation_limit_height,
    )
    return callable_method(**kwargs)
