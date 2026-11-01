"""Limit-switch alarm recovery helpers for CubOS gantry motion."""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .errors import CommandExecutionError, MillConnectionError, StatusReturnError

STATUS_QUERY_FAILED = "StatusQueryFailed"


@dataclass(frozen=True)
class LimitRecoveryResult:
    """Summary of a completed limit-switch pull-off recovery."""

    failed_delta: dict[str, float] | None
    pull_off_delta: dict[str, float]
    attempts: int
    final_status: str | None
    mode: str = "known_jog"
    commanded_delta: dict[str, float] | None = None


def looks_like_limit_alarm(value: Exception | str) -> bool:
    """Return true when a controller error/status looks like a limit alarm."""
    message = str(value).lower()
    pins = re.search(r"Pn:([^|>;\s]*)", message, re.IGNORECASE)
    return (
        any(token in message for token in ("alarm", "check limits", "hard limit", "soft limit", "limit pin active"))
        or re.search(r"error:9(?:\D|$)", message) is not None
        or bool(pins and any(axis in pins.group(1) for axis in "xyz"))
    )


def opposite_pull_off_delta(
    delta: Mapping[str, float],
    pull_off_mm: float,
) -> dict[str, float]:
    """Return a pull-off vector opposite a failed jog vector."""
    pull_off = {"x": 0.0, "y": 0.0, "z": 0.0}
    for axis, value in delta.items():
        if value == 0:
            continue
        if value > 0:
            pull_off[axis] = -pull_off_mm
        else:
            pull_off[axis] = pull_off_mm
    return pull_off


def raise_if_limit_status(status: str) -> None:
    """Raise when a GRBL status string shows alarm or active limit pins."""
    lower_status = status.lower()
    if "alarm" in lower_status:
        raise StatusReturnError(f"Alarm in status: {status}")
    # GRBL reports active limit pins as Pn:X, Pn:Y, Pn:Z (possibly combined).
    if "pn:" in lower_status:
        pin_text = lower_status.split("pn:", 1)[1].split("|", 1)[0].split(">", 1)[0]
        if any(axis in pin_text for axis in ("x", "y", "z")):
            raise StatusReturnError(f"Limit pin active in status: {status}")


def probe_for_limit_status_after_jog(gantry: Any, *, delay_s: float = 0.05) -> None:
    """Check for late jog alarms; connection and status failures propagate."""
    get_status = getattr(gantry, "get_status", None)
    if not callable(get_status):
        logging.getLogger(__name__).warning(
            "probe_for_limit_status_after_jog: gantry has no get_status method; "
            "post-jog limit probe skipped — late limit alarms will not be detected"
        )
        return
    if delay_s > 0:
        time.sleep(delay_s)
    raise_if_limit_status(str(get_status()))


def soft_reset_and_unlock_after_limit_alarm(
    gantry: Any,
    *,
    output: Callable[[str], None],
    confirmed_limit_axis: str | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> None:
    """Soft-reset GRBL, then unlock so a pull-off jog can be attempted."""
    method = "reset_and_unlock_for_limit_recovery" if confirmed_limit_axis else "reset_and_unlock"
    reset_and_unlock = getattr(gantry, method, None)
    if not callable(reset_and_unlock):
        raise CommandExecutionError(
            f"Limit recovery requires gantry.{method}() so GRBL gets "
            "a soft reset (Ctrl-X) before $X unlock."
        )
    try:
        output("Soft-resetting GRBL, then unlocking before pull-off.")
        if confirmed_limit_axis:
            notices = reset_and_unlock(axis=confirmed_limit_axis, check_cancelled=check_cancelled)
            for notice in notices or []:
                output(f"Reset notice: {notice}")
        else:
            reset_and_unlock()
    except MillConnectionError:
        raise
    except (CommandExecutionError, StatusReturnError) as exc:
        output(f"Soft reset/unlock during limit recovery failed: {exc}")
        output("Use the controller/E-stop reset path before continuing.")
        raise


def read_limit_recovery_status(gantry: Any) -> str | None:
    """Read recovery status without hiding connection or status failures."""
    get_status = getattr(gantry, "get_status", None)
    if not callable(get_status):
        return None
    return str(get_status())


def needs_another_limit_pull_off(status: str | None) -> bool:
    """Return true when status still indicates an uncleared limit/alarm state."""
    if status is None:
        return False
    lower = status.lower()
    return any(
        token in lower
        for token in (
            "alarm",
            "reset to continue",
            "hard limit",
            "limit",
            "pn:",
            "statusqueryfailed",
            # "failed" intentionally omitted: already covered by "statusqueryfailed"
            # and too broad — matches unrelated GRBL status strings.
        )
    )


def recover_from_limit_alarm(
    gantry: Any,
    delta: Mapping[str, float],
    *,
    pull_off_mm: float,
    feed_rate: float,
    output: Callable[[str], None],
    max_pull_off_attempts: int = 1,
    timeout_s: float = 10.0,
    cancelled: Callable[[], bool] | None = None,
    confirmed_limit_axis: str | None = None,
    manual: bool = False,
) -> LimitRecoveryResult:
    """Attempt one directed pull-off and verify it stopped clear of the switch."""
    if max_pull_off_attempts != 1:
        raise ValueError("max_pull_off_attempts must be 1; inspect before another pull-off.")
    normalized_delta = {axis: float(delta.get(axis, 0.0)) for axis in ("x", "y", "z")}
    if not all(math.isfinite(value) for value in normalized_delta.values()) or not any(normalized_delta.values()):
        raise ValueError("Limit recovery requires a finite, nonzero failed jog delta.")
    moving_axes = [axis for axis, value in normalized_delta.items() if value]
    if confirmed_limit_axis is not None and (
        confirmed_limit_axis not in ("x", "y", "z") or moving_axes != [confirmed_limit_axis]
    ):
        raise ValueError("Confirmed-axis recovery requires a matching single-axis jog.")
    if manual and (confirmed_limit_axis is None or pull_off_mm != 1.0 or feed_rate != 100.0):
        raise ValueError("Manual recovery requires a confirmed axis and one 1 mm move at 100 mm/min.")
    if not math.isfinite(pull_off_mm) or pull_off_mm <= 0:
        raise ValueError("pull_off_mm must be finite and positive.")
    if not math.isfinite(feed_rate) or feed_rate <= 0:
        raise ValueError("feed_rate must be finite and positive.")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be finite and positive.")
    status_method = "get_recovery_status" if confirmed_limit_axis else "get_status"
    get_status = getattr(gantry, status_method, None)
    if not callable(get_status):
        raise StatusReturnError("Limit recovery requires controller status verification.")
    jog_method = "jog_for_limit_recovery" if confirmed_limit_axis else "jog"
    recovery_jog = getattr(gantry, jog_method, None)
    if confirmed_limit_axis and not callable(recovery_jog):
        raise CommandExecutionError(f"Limit recovery requires gantry.{jog_method}().")

    def check_cancelled() -> None:
        if cancelled is not None and cancelled():
            raise CommandExecutionError("Limit recovery cancelled; inspect before moving again.")

    effective_pull_off = float(pull_off_mm) if manual else max(5.0, float(pull_off_mm))
    pull_off = opposite_pull_off_delta(normalized_delta, effective_pull_off)
    output("Attempting one operator-confirmed 1 mm pull-off." if manual else "Limit alarm detected. Attempting one pull-off opposite the failed jog.")
    check_cancelled()
    gantry.jog_cancel()
    check_cancelled()
    soft_reset_and_unlock_after_limit_alarm(
        gantry, output=output, confirmed_limit_axis=confirmed_limit_axis,
        check_cancelled=check_cancelled,
    )
    check_cancelled()
    if confirmed_limit_axis:
        status = str(get_status())
        pins = re.search(r"Pn:([^|>;\s]*)", status, re.IGNORECASE)
        if pins is None or set(pins.group(1).upper()) != {confirmed_limit_axis.upper()}:
            raise StatusReturnError(f"Active {confirmed_limit_axis.upper()} switch did not verify after reset/unlock: {status}")
        if not re.match(r"^<?idle(?:[|>]|$)", status, re.IGNORECASE):
            raise StatusReturnError(f"Controller is not ready for a {confirmed_limit_axis.upper()} pull-off: {status}")
        output(f"Before pull-off: {status}")
    check_cancelled()
    if confirmed_limit_axis:
        recovery_jog(feed_rate=feed_rate, check_cancelled=check_cancelled, **pull_off)
    else:
        recovery_jog(feed_rate=feed_rate, **pull_off)
    deadline = time.monotonic() + timeout_s
    while True:
        check_cancelled()
        status = str(get_status())
        check_cancelled()
        lowered = status.lower()
        if "alarm" in lowered or "error:" in lowered or "check limits" in lowered:
            raise StatusReturnError(f"Limit pull-off did not clear the alarm: {status}")
        if re.match(r"^<?idle(?:[|>]|$)", lowered):
            raise_if_limit_status(status)
            output("Pulled off the limit switch; controller is Idle with no active limit pins.")
            return LimitRecoveryResult(
                failed_delta=None if manual else normalized_delta,
                pull_off_delta=pull_off,
                attempts=1,
                final_status=status,
                mode="manual" if manual else "known_jog",
                commanded_delta=dict(pull_off),
            )
        if not re.match(r"^<?(?:jog|run)(?:[|>]|$)", lowered):
            raise StatusReturnError(f"Limit recovery status is unverified: {status}")
        if time.monotonic() >= deadline:
            gantry.jog_cancel()
            raise StatusReturnError(f"Limit recovery timed out waiting for Idle: {status}")
        time.sleep(0.1)
