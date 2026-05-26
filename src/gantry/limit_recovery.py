"""Limit-switch alarm recovery helpers for CubOS gantry motion."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .errors import CommandExecutionError, MillConnectionError, StatusReturnError

STATUS_QUERY_FAILED = "StatusQueryFailed"


@dataclass(frozen=True)
class LimitRecoveryResult:
    """Summary of a completed limit-switch pull-off recovery."""

    failed_delta: dict[str, float]
    pull_off_delta: dict[str, float]
    attempts: int
    final_status: str | None


def looks_like_limit_alarm(value: Exception | str) -> bool:
    """Return true when a controller error/status looks like a limit alarm."""
    message = str(value).lower()
    return any(
        token in message
        for token in (
            "alarm",
            "check limits",
            "hard limit",
            "limit",
            "pn:",
            "error:9",
        )
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
    """Check status shortly after a jog to catch controllers that alarm late.

    Unlike read_limit_recovery_status, this does NOT catch MillConnectionError —
    a connection drop after a jog is a fatal condition that should abort the
    calling operation, not trigger a retry.
    """
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
) -> None:
    """Soft-reset GRBL, then unlock so a pull-off jog can be attempted."""
    reset_and_unlock = getattr(gantry, "reset_and_unlock", None)
    if not callable(reset_and_unlock):
        raise CommandExecutionError(
            "Limit recovery requires gantry.reset_and_unlock() so GRBL gets "
            "a soft reset (Ctrl-X) before $X unlock."
        )
    try:
        output("Soft-resetting GRBL, then unlocking before pull-off.")
        reset_and_unlock()
    except MillConnectionError:
        raise
    except (CommandExecutionError, StatusReturnError) as exc:
        output(f"Soft reset/unlock during limit recovery failed: {exc}")
        output("Use the controller/E-stop reset path before continuing.")
        raise


def read_limit_recovery_status(gantry: Any) -> str | None:
    """Read controller status during recovery.

    ``None`` means the gantry object has no status API. A status-read exception
    is different: after a hard limit, GRBL can still be in alarm or too busy to
    answer. Treat that as unverified recovery so callers retry or fail closed.
    """
    get_status = getattr(gantry, "get_status", None)
    if not callable(get_status):
        return None
    try:
        return str(get_status())
    except (StatusReturnError, MillConnectionError) as exc:
        logging.getLogger(__name__).warning(
            "Status read failed during limit recovery; retrying pull-off "
            "before reporting recovery: %s",
            exc,
        )
        return f"{STATUS_QUERY_FAILED}: {exc}"


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
    max_pull_off_attempts: int = 5,
) -> LimitRecoveryResult:
    """Clear a GRBL limit alarm and pull off opposite the failed jog vector."""
    if max_pull_off_attempts <= 0:
        raise ValueError(
            f"max_pull_off_attempts must be > 0; got {max_pull_off_attempts}"
        )
    effective_pull_off_mm = max(5.0, float(pull_off_mm))
    normalized_delta = {
        "x": float(delta.get("x", 0.0)),
        "y": float(delta.get("y", 0.0)),
        "z": float(delta.get("z", 0.0)),
    }
    pull_off = opposite_pull_off_delta(normalized_delta, effective_pull_off_mm)
    failed_direction = ", ".join(
        f"{axis.upper()}{value:+g} mm"
        for axis, value in normalized_delta.items()
        if value
    ) or "unknown direction"
    pull_off_direction = ", ".join(
        f"{axis.upper()}{value:+g} mm" for axis, value in pull_off.items() if value
    ) or "unknown direction"
    output(
        "Limit alarm detected while jogging "
        f"{failed_direction}. Soft-resetting/unlocking GRBL and pulling off "
        f"{pull_off_direction} at {feed_rate:g} mm/min."
    )
    try:
        gantry.jog_cancel()
    except MillConnectionError:
        raise
    except (CommandExecutionError, StatusReturnError) as exc:
        output(f"Jog cancel during recovery failed: {exc}")
        output("Aborting calibration; use E-stop and rerun before continuing.")
        raise

    output(
        f"Attempting limit pull-off up to {max_pull_off_attempts} times; "
        "soft-resetting/unlocking between attempts."
    )
    final_status: str | None = None
    for attempt in range(1, max_pull_off_attempts + 1):
        soft_reset_and_unlock_after_limit_alarm(gantry, output=output)
        try:
            gantry.jog(feed_rate=feed_rate, **pull_off)
        except MillConnectionError:
            raise
        except (CommandExecutionError, StatusReturnError) as exc:
            if attempt >= max_pull_off_attempts:
                output(f"Limit pull-off failed after {max_pull_off_attempts} attempts: {exc}")
                output("Aborting calibration; gantry position is unknown.")
                raise
            output(
                f"Limit pull-off attempt {attempt}/{max_pull_off_attempts} did not clear; retrying."
            )
            continue

        final_status = read_limit_recovery_status(gantry)
        if not needs_another_limit_pull_off(final_status):
            output(
                "Pulled off the limit switch. Skipping immediate WPos readback because "
                "GRBL may not report coordinates reliably right after a limit reset; "
                "position readback will resume on the next operator confirmation."
            )
            return LimitRecoveryResult(
                failed_delta=normalized_delta,
                pull_off_delta=pull_off,
                attempts=attempt,
                final_status=final_status,
            )
        if attempt >= max_pull_off_attempts:
            if final_status and final_status.startswith(STATUS_QUERY_FAILED):
                output(
                    "Limit recovery could not verify controller status after "
                    f"{max_pull_off_attempts} pull-off attempts. Use E-stop/power "
                    "reset and manually clear the switch before continuing."
                )
                raise StatusReturnError(
                    "Limit recovery could not verify the controller cleared the alarm "
                    "after repeated status read failures."
                )
            output(
                "Pull-off jog still left the controller in a limit/alarm state "
                f"after {max_pull_off_attempts} attempts. Use E-stop/power reset "
                "and manually clear the switch before continuing."
            )
            raise StatusReturnError(
                "Limit pull-off did not clear the alarm after repeated attempts."
            )
        output(
            f"Limit pull-off attempt {attempt}/{max_pull_off_attempts} did not clear; retrying."
        )
