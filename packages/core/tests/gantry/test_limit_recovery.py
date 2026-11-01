"""Unit tests for reusable gantry limit-switch recovery helpers."""

from __future__ import annotations

import pytest

from cubos.gantry.errors import CommandExecutionError, MillConnectionError, StatusReturnError
from cubos.gantry.limit_recovery import (
    looks_like_limit_alarm,
    needs_another_limit_pull_off,
    opposite_pull_off_delta,
    recover_from_limit_alarm,
)


class _RecoveringGantry:
    def __init__(self, statuses: list[str | Exception] | None = None):
        self.calls: list[tuple] = []
        self.statuses = list(statuses or ["Idle"])

    def jog_for_limit_recovery(self, *, check_cancelled=None, **kwargs):
        if check_cancelled is not None:
            check_cancelled()
        return self.jog(**kwargs)

    def jog_cancel(self) -> None:
        self.calls.append(("jog_cancel",))

    def reset_and_unlock(self) -> None:
        self.calls.append(("reset_and_unlock",))

    def jog(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        feed_rate: float = 2000,
    ) -> None:
        self.calls.append(("jog", x, y, z, feed_rate))

    def get_recovery_status(self) -> str:
        return self.get_status()

    def get_status(self) -> str:
        self.calls.append(("get_status",))
        if not self.statuses:
            return "Idle"
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        return status


def test_recover_from_limit_alarm_resets_unlocks_and_pulls_off_opposite_delta():
    messages: list[str] = []
    gantry = _RecoveringGantry()

    result = recover_from_limit_alarm(
        gantry,
        {"x": 1.0, "y": 0.0, "z": -0.5},
        pull_off_mm=2.0,
        feed_rate=2500.0,
        output=messages.append,
    )

    assert result.attempts == 1
    assert result.pull_off_delta == {"x": -5.0, "y": 0.0, "z": 5.0}
    assert gantry.calls == [
        ("jog_cancel",),
        ("reset_and_unlock",),
        ("jog", -5.0, 0.0, 5.0, 2500.0),
        ("get_status",),
    ]
    assert any("Limit alarm detected" in message for message in messages)
    assert any("Pulled off the limit switch" in message for message in messages)


@pytest.mark.parametrize(
    "failure",
    [
        "<Alarm|Pn:Z>",
        "<Idle|Pn:Z>",
        "<Hold:0|WPos:0,0,0>",
        "[MSG:Check Limits]",
        "ok",
        StatusReturnError("Failed to get status from the mill"),
        MillConnectionError("USB disconnected"),
    ],
)
def test_recovery_faults_stop_without_another_reset_or_jog(failure):
    gantry = _RecoveringGantry([failure])
    expected = type(failure) if isinstance(failure, Exception) else StatusReturnError

    with pytest.raises(expected):
        recover_from_limit_alarm(
            gantry, {"z": -1}, pull_off_mm=5, feed_rate=800, output=lambda _: None,
        )

    assert gantry.calls.count(("reset_and_unlock",)) == 1
    assert gantry.calls.count(("jog", 0, 0, 5, 800)) == 1
    assert gantry.calls.count(("get_status",)) == 1


def test_recovery_waits_for_jog_completion_without_another_move(monkeypatch):
    monkeypatch.setattr("cubos.gantry.limit_recovery.time.sleep", lambda _: None)
    gantry = _RecoveringGantry(["<Jog|Pn:Z>", "<Jog|WPos:0,0,0>", "<Idle|WPos:0,0,0>"])

    result = recover_from_limit_alarm(
        gantry, {"z": 1}, pull_off_mm=5, feed_rate=800, output=lambda _: None,
    )

    assert result.attempts == 1
    assert result.final_status == "<Idle|WPos:0,0,0>"
    assert gantry.calls.count(("reset_and_unlock",)) == 1
    assert gantry.calls.count(("jog", 0, 0, -5, 800)) == 1
    assert gantry.calls.count(("get_status",)) == 3


def test_recovery_timeout_cancels_without_retry(monkeypatch):
    monkeypatch.setattr("cubos.gantry.limit_recovery.time.monotonic", iter([0, 11]).__next__)
    gantry = _RecoveringGantry(["<Jog|Pn:Z>"])

    with pytest.raises(StatusReturnError, match="timed out"):
        recover_from_limit_alarm(
            gantry, {"z": 1}, pull_off_mm=5, feed_rate=800, output=lambda _: None,
        )

    assert gantry.calls.count(("jog_cancel",)) == 2
    assert gantry.calls.count(("reset_and_unlock",)) == 1
    assert gantry.calls.count(("jog", 0, 0, -5, 800)) == 1


@pytest.mark.parametrize("cancel_check", [1, 2, 3, 4, 5])
def test_recovery_cancel_never_restarts_motion(cancel_check):
    gantry = _RecoveringGantry()
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= cancel_check

    with pytest.raises(CommandExecutionError, match="cancelled"):
        recover_from_limit_alarm(
            gantry, {"z": 1}, pull_off_mm=5, feed_rate=800,
            output=lambda _: None, cancelled=cancelled,
        )

    assert gantry.calls.count(("reset_and_unlock",)) <= 1
    assert gantry.calls.count(("jog", 0, 0, -5, 800)) == (1 if cancel_check == 5 else 0)
    assert not any(call[0] in ("home", "reconnect") for call in gantry.calls)


def test_recovery_rejected_jog_never_retries():
    class RejectedGantry(_RecoveringGantry):
        def jog(self, **kwargs):
            super().jog(**kwargs)
            raise CommandExecutionError("ALARM:1")

    gantry = RejectedGantry()
    with pytest.raises(CommandExecutionError):
        recover_from_limit_alarm(
            gantry, {"z": 1}, pull_off_mm=5, feed_rate=800, output=lambda _: None,
        )

    assert gantry.calls == [("jog_cancel",), ("reset_and_unlock",), ("jog", 0, 0, -5, 800)]


@pytest.mark.parametrize(
    "text",
    [
        "ALARM:1 hard limit",
        "error:9 Reset to continue",
        "<Idle|Pn:X>",
        "Jog failed: check limits",
    ],
)
def test_looks_like_limit_alarm_covers_grbl_alarm_text(text: str):
    assert looks_like_limit_alarm(text) is True


# ---------------------------------------------------------------------------
# MillConnectionError propagation
# ---------------------------------------------------------------------------


def test_mill_connection_error_from_jog_cancel_propagates():
    class FailingJogCancel(_RecoveringGantry):
        def jog_cancel(self) -> None:
            raise MillConnectionError("serial disconnected")

    gantry = FailingJogCancel()
    with pytest.raises(MillConnectionError, match="serial disconnected"):
        recover_from_limit_alarm(
            gantry,
            {"x": 1.0, "y": 0.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=lambda _: None,
        )


def test_mill_connection_error_from_pull_off_jog_propagates():
    class FailingJog(_RecoveringGantry):
        def jog(self, x=0, y=0, z=0, feed_rate=2000) -> None:
            raise MillConnectionError("serial disconnected during pull-off")

    gantry = FailingJog()
    with pytest.raises(MillConnectionError, match="serial disconnected"):
        recover_from_limit_alarm(
            gantry,
            {"x": 0.0, "y": 1.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=lambda _: None,
        )


def test_mill_connection_error_from_reset_and_unlock_propagates():
    class FailingReset(_RecoveringGantry):
        def reset_and_unlock(self) -> None:
            raise MillConnectionError("serial disconnected during reset")

    gantry = FailingReset()
    with pytest.raises(MillConnectionError, match="serial disconnected"):
        recover_from_limit_alarm(
            gantry,
            {"x": 0.0, "y": 0.0, "z": -1.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=lambda _: None,
        )


# ---------------------------------------------------------------------------
# jog_cancel and reset_and_unlock failure paths
# ---------------------------------------------------------------------------


def test_jog_cancel_command_execution_error_propagates():
    messages: list[str] = []

    class FailingJogCancel(_RecoveringGantry):
        def jog_cancel(self) -> None:
            raise CommandExecutionError("ALARM:1")

    gantry = FailingJogCancel()
    with pytest.raises(CommandExecutionError):
        recover_from_limit_alarm(
            gantry,
            {"x": 1.0, "y": 0.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=messages.append,
        )

    assert not any(call[0] == "reset_and_unlock" for call in gantry.calls)
    assert not any(m for m in messages if "Attempting limit pull-off" in m)


def test_reset_and_unlock_failure_propagates_before_retry():
    messages: list[str] = []

    class FailingReset(_RecoveringGantry):
        def reset_and_unlock(self) -> None:
            raise CommandExecutionError("reset failed")

    gantry = FailingReset()
    with pytest.raises(CommandExecutionError, match="reset failed"):
        recover_from_limit_alarm(
            gantry,
            {"x": 0.0, "y": -1.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=messages.append,
        )

    assert any("E-stop" in m for m in messages)
    assert gantry.calls.count(("jog_cancel",)) == 1
    # jog should never have been reached
    assert not any(c[0] == "jog" for c in gantry.calls)


def test_missing_reset_and_unlock_raises_command_execution_error():
    class NoResetGantry:
        calls: list[tuple] = []

        def jog_cancel(self) -> None:
            self.calls.append(("jog_cancel",))

        def get_status(self) -> str:
            return "Idle"

    gantry = NoResetGantry()
    with pytest.raises(CommandExecutionError, match="reset_and_unlock"):
        recover_from_limit_alarm(
            gantry,
            {"x": 1.0, "y": 0.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=lambda _: None,
        )


# ---------------------------------------------------------------------------
# needs_another_limit_pull_off negative cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        "<Idle|WPos:0,0,0>",
        "<Run|WPos:10,5,3>",
        "Ok",
        None,
    ],
)
def test_needs_another_limit_pull_off_false_for_healthy_status(status: str | None):
    assert needs_another_limit_pull_off(status) is False


def test_needs_another_limit_pull_off_does_not_match_bare_failed_word():
    # "failed" alone must not trigger a pull-off; only "statusqueryfailed" should.
    assert needs_another_limit_pull_off("some-operation-failed") is False
    assert needs_another_limit_pull_off("StatusQueryFailed: connection lost") is True


# ---------------------------------------------------------------------------
# recover_from_limit_alarm — invalid arguments
# ---------------------------------------------------------------------------


def test_recover_from_limit_alarm_raises_value_error_for_zero_attempts():
    with pytest.raises(ValueError, match="max_pull_off_attempts"):
        recover_from_limit_alarm(
            _RecoveringGantry(),
            {"x": 1.0, "y": 0.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=lambda _: None,
            max_pull_off_attempts=0,
        )


def test_recover_from_limit_alarm_raises_value_error_for_negative_attempts():
    with pytest.raises(ValueError, match="max_pull_off_attempts"):
        recover_from_limit_alarm(
            _RecoveringGantry(),
            {"x": 1.0, "y": 0.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2000.0,
            output=lambda _: None,
            max_pull_off_attempts=-1,
        )


# ---------------------------------------------------------------------------
# opposite_pull_off_delta
# ---------------------------------------------------------------------------


def test_opposite_pull_off_delta_returns_no_op_for_all_zero_delta():
    result = opposite_pull_off_delta({"x": 0.0, "y": 0.0, "z": 0.0}, pull_off_mm=5.0)
    assert result == {"x": 0.0, "y": 0.0, "z": 0.0}


def test_opposite_pull_off_delta_covers_xy_simultaneous_case():
    result = opposite_pull_off_delta({"x": 1.0, "y": -0.5, "z": 0.0}, pull_off_mm=5.0)
    assert result["x"] == -5.0
    assert result["y"] == 5.0
    assert result["z"] == 0.0


# ---------------------------------------------------------------------------
# looks_like_limit_alarm — false-positive guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "<Idle|WPos:0,0,0>",
        "<Run|MPos:10,5,3>",
        "ok",
        "Jog",
    ],
)
def test_looks_like_limit_alarm_false_for_non_alarm_strings(text: str):
    assert looks_like_limit_alarm(text) is False


@pytest.mark.parametrize("status", ["<Idle|Pn:P>", "<Idle|Pn:>", "error:90", None])
def test_non_limit_pin_or_unrelated_error_does_not_match_limit_alarm(status):
    assert not looks_like_limit_alarm(status)


@pytest.mark.parametrize(
    "kwargs",
    [{"pull_off_mm": 0}, {"pull_off_mm": float("nan")}, {"feed_rate": 0}, {"feed_rate": float("inf")}, {"timeout_s": 0}, {"timeout_s": float("nan")}, {"max_pull_off_attempts": 2}],
)
def test_invalid_recovery_parameters_never_actuate(kwargs):
    gantry = _RecoveringGantry()
    params = {"pull_off_mm": 5, "feed_rate": 800, "output": lambda _: None, **kwargs}

    with pytest.raises(ValueError):
        recover_from_limit_alarm(gantry, {"z": -1}, **params)

    assert not gantry.calls


def test_active_z_acknowledgement_cannot_authorize_xy_pull_off():
    gantry = _RecoveringGantry()
    with pytest.raises(ValueError, match="matching single-axis"):
        recover_from_limit_alarm(
            gantry, {"x": 1}, pull_off_mm=5, feed_rate=800,
            output=lambda _: None, confirmed_limit_axis="z",
        )
    assert not gantry.calls


@pytest.mark.parametrize("status", ["<Idle>", "<Idle|Pn:XZ>", "<Idle|Pn:ZP>", "<Alarm|Pn:Z>", "<Jog|Pn:Z>"])
def test_guarded_recovery_rechecks_switch_and_idle_after_reset_before_jog(status):
    class ActiveZRecovery(_RecoveringGantry):
        def reset_and_unlock_for_limit_recovery(self, *, axis, check_cancelled=None):
            self.calls.append(("guarded_reset_and_unlock",))

    gantry = ActiveZRecovery([status])
    with pytest.raises(StatusReturnError):
        recover_from_limit_alarm(
            gantry, {"z": -1}, pull_off_mm=5, feed_rate=800,
            output=lambda _: None, confirmed_limit_axis="z",
        )

    assert gantry.calls == [("jog_cancel",), ("guarded_reset_and_unlock",), ("get_status",)]


@pytest.mark.parametrize("delta", [{}, {"z": float("nan")}, {"z": float("inf")}])
def test_recovery_without_finite_direction_never_actuates(delta):
    gantry = _RecoveringGantry()
    with pytest.raises(ValueError, match="nonzero failed jog"):
        recover_from_limit_alarm(gantry, delta, pull_off_mm=5, feed_rate=800, output=lambda _: None)
    assert not gantry.calls


def test_recovery_without_status_api_never_actuates():
    gantry = _RecoveringGantry()
    gantry.get_status = None
    with pytest.raises(StatusReturnError, match="verification"):
        recover_from_limit_alarm(gantry, {"z": -1}, pull_off_mm=5, feed_rate=800, output=lambda _: None)
    assert not gantry.calls


def test_verified_recovery_requires_scoped_jog_method_before_any_actuation():
    gantry = _RecoveringGantry()
    gantry.jog_for_limit_recovery = None
    with pytest.raises(CommandExecutionError, match="jog_for_limit_recovery"):
        recover_from_limit_alarm(
            gantry, {"y": -1}, pull_off_mm=5, feed_rate=100,
            output=lambda _: None, confirmed_limit_axis="y",
        )
    assert not gantry.calls
