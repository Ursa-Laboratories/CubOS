"""Shared method-dispatch helpers used by engaging protocol commands.

Most instrument methods are open-loop: a protocol command pre-positions
the gantry, then invokes the method to act at that pose. Some methods
are closed-loop and need to drive the gantry themselves during the
action — ASMI.indentation steps Z and reads force in a feedback loop.
Those methods declare a ``gantry`` parameter.

Naming convention (the same one used across the protocol layer):

* ``[name]_z`` — absolute deck-frame Z (WPos).
* ``[name]_height`` — labware-relative offset (mm above the well/labware
  surface; +above, -below).

The dispatch helper forwards user-supplied YAML fields under their
original names (``measurement_height``, ``indentation_limit_height``)
and also injects an absolute reference Z (``well_z``) so closed-loop
methods can compute their own action / target Z values from a single
labware-surface anchor.
"""

from __future__ import annotations

import inspect
import math
from typing import Any, Callable, Dict, TYPE_CHECKING

from ..errors import ProtocolExecutionError

if TYPE_CHECKING:
    from ..protocol import ProtocolContext


def _assert_finite(value: Any, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ProtocolExecutionError(
            f"{name} must be a finite number, got "
            f"{type(value).__name__} {value!r}."
        )


def inject_runtime_args(
    callable_method: Callable[..., Any],
    method_kwargs: Dict[str, Any],
    context: "ProtocolContext",
    *,
    well_z: float,
    measurement_height: float | None = None,
    indentation_limit_height: float | None = None,
) -> Dict[str, Any]:
    """Return a fresh kwargs dict with runtime-injected args added.

    Injects when the method's signature declares the parameter:
      * ``gantry`` — from ``context.gantry.controller``.
      * ``well_z`` — absolute deck-frame Z of the labware surface
        (engine-resolved from the calibration anchor).
      * ``measurement_height`` — labware-relative action plane offset
        (mm above ``well_z``), forwarded from the protocol command.
        Optional; only injected when supplied and the method declares it.
      * ``indentation_limit_height`` — labware-relative deepest plane
        offset, forwarded from the protocol command. Optional.

    Runtime injection is the source of truth: when the engine has a value
    that reflects physical state, it overrides whatever ``method_kwargs``
    carried. ``scan_args._LEGACY_KWARG_HINTS`` rejects YAML-supplied
    duplicates of the relative offsets at load time.

    ``well_z`` is a required keyword: callers always have a resolved
    absolute reference Z to forward. Tests of pure gantry-injection
    behavior pass any finite sentinel (e.g. ``0.0``).

    Raises:
        ProtocolExecutionError: if any injected value is not a finite
            number, if the method declares ``gantry`` but
            ``context.gantry.controller`` is None, if a method requires a
            relative offset that wasn't supplied, or if a relative offset
            was supplied to a method that doesn't declare one (silently
            dropping a depth bound on a misconfigured scan would be
            worse than a clear command-boundary error).
    """
    _assert_finite(well_z, "well_z")
    if measurement_height is not None:
        _assert_finite(measurement_height, "measurement_height")
    if indentation_limit_height is not None:
        _assert_finite(indentation_limit_height, "indentation_limit_height")

    kwargs: Dict[str, Any] = dict(method_kwargs)
    sig = inspect.signature(callable_method)
    if "gantry" in sig.parameters:
        if context.gantry.controller is None:
            raise ProtocolExecutionError(
                f"Method {callable_method.__qualname__!r} declares a `gantry` "
                "parameter but `context.gantry.controller` is None. Closed-loop "
                "methods need an attached gantry."
            )
        kwargs["gantry"] = context.gantry.controller
    if "well_z" in sig.parameters:
        kwargs["well_z"] = well_z

    # ``measurement_height`` is always present on the engine side
    # (required on scan/measure). Inject when the method declares it;
    # silent skip is fine for open-loop methods that don't consume it.
    if measurement_height is not None and "measurement_height" in sig.parameters:
        kwargs["measurement_height"] = measurement_height
    elif (
        "measurement_height" in sig.parameters
        and measurement_height is None
        and sig.parameters["measurement_height"].default is inspect.Parameter.empty
    ):
        raise ProtocolExecutionError(
            f"Method {callable_method.__qualname__!r} requires "
            "`measurement_height`, which the engine forwards from the "
            "protocol command. Add `measurement_height` to the "
            "scan/measure command."
        )

    # ``indentation_limit_height`` is *user-conditional* — only present
    # when the YAML scan command supplies it. If the user supplied it
    # but the method doesn't declare it, the resolved depth bound would
    # be silently dropped (e.g. ``method: indent`` typo for
    # ``method: indentation``). Surface as a command-boundary error.
    if (
        indentation_limit_height is not None
        and "indentation_limit_height" in sig.parameters
    ):
        kwargs["indentation_limit_height"] = indentation_limit_height
    elif (
        indentation_limit_height is not None
        and "indentation_limit_height" not in sig.parameters
    ):
        raise ProtocolExecutionError(
            f"Method {callable_method.__qualname__!r} does not declare an "
            "`indentation_limit_height` parameter, but the scan command "
            "supplied one — the resolved depth bound would be silently "
            "ignored. Drop `indentation_limit_height` from the scan "
            "command or use a method that consumes it (e.g. ASMI "
            "`indentation`)."
        )
    elif (
        "indentation_limit_height" in sig.parameters
        and indentation_limit_height is None
        and sig.parameters["indentation_limit_height"].default is inspect.Parameter.empty
    ):
        raise ProtocolExecutionError(
            f"Method {callable_method.__qualname__!r} requires "
            "`indentation_limit_height`, which the engine forwards from "
            "the scan command. Add `indentation_limit_height` (signed "
            "labware-relative offset; negative = below the well surface) "
            "to the scan command."
        )
    return kwargs
