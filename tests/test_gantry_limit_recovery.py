"""Unit tests for reusable gantry limit-switch recovery helpers."""

from __future__ import annotations

import pytest

from gantry.errors import CommandExecutionError, MillConnectionError, StatusReturnError
from gantry.limit_recovery import (
    looks_like_limit_alarm,
    needs_another_limit_pull_off,
    opposite_pull_off_delta,
    recover_from_limit_alarm,
)


class _RecoveringGantry:
    def __init__(self, statuses: list[str | Exception] | None = None):
        self.calls: list[tuple] = []
        self.statuses = list(statuses or ["Idle"])

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


def test_recover_from_limit_alarm_retries_status_that_still_reports_limit():
    messages: list[str] = []
    gantry = _RecoveringGantry(["<Alarm|Pn:X>", "<Idle|WPos:0,0,0>"])

    result = recover_from_limit_alarm(
        gantry,
        {"x": -1.0, "y": 0.0, "z": 0.0},
        pull_off_mm=6.0,
        feed_rate=1200.0,
        output=messages.append,
    )

    assert result.attempts == 2
    assert gantry.calls.count(("reset_and_unlock",)) == 2
    assert gantry.calls.count(("jog", 6.0, 0.0, 0.0, 1200.0)) == 2
    assert any("1/5 did not clear" in message for message in messages)


def test_recover_from_limit_alarm_retries_failed_status_read_before_success():
    messages: list[str] = []
    gantry = _RecoveringGantry(
        [
            StatusReturnError("Failed to get status from the mill"),
            "<Idle|WPos:0,0,0>",
        ]
    )

    result = recover_from_limit_alarm(
        gantry,
        {"x": 1.0, "y": 0.0, "z": 0.0},
        pull_off_mm=5.0,
        feed_rate=1000.0,
        output=messages.append,
    )

    assert result.attempts == 2
    assert result.final_status == "<Idle|WPos:0,0,0>"
    assert gantry.calls.count(("reset_and_unlock",)) == 2
    assert gantry.calls.count(("jog", -5.0, 0.0, 0.0, 1000.0)) == 2
    assert any("1/5 did not clear" in message for message in messages)


def test_recover_from_limit_alarm_raises_after_five_uncleared_attempts():
    messages: list[str] = []
    gantry = _RecoveringGantry(["<Alarm|Pn:Y>"] * 5)

    with pytest.raises(StatusReturnError, match="did not clear"):
        recover_from_limit_alarm(
            gantry,
            {"x": 0.0, "y": -1.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=2500.0,
            output=messages.append,
        )

    assert gantry.calls.count(("reset_and_unlock",)) == 5
    assert gantry.calls.count(("jog", 0.0, 5.0, 0.0, 2500.0)) == 5
    assert any("after 5 attempts" in message for message in messages)


def test_recover_from_limit_alarm_raises_after_repeated_status_read_failures():
    messages: list[str] = []
    gantry = _RecoveringGantry(
        [StatusReturnError("Failed to get status from the mill")] * 5
    )

    with pytest.raises(StatusReturnError, match="could not verify"):
        recover_from_limit_alarm(
            gantry,
            {"x": 0.0, "y": 1.0, "z": 0.0},
            pull_off_mm=5.0,
            feed_rate=800.0,
            output=messages.append,
        )

    assert gantry.calls.count(("reset_and_unlock",)) == 5
    assert gantry.calls.count(("jog", 0.0, -5.0, 0.0, 800.0)) == 5
    assert any("could not verify controller status" in message for message in messages)


def test_recover_from_limit_alarm_retries_failed_pull_off_jog_until_success():
    messages: list[str] = []

    class RetryingGantry(_RecoveringGantry):
        def __init__(self):
            super().__init__(["Idle"])
            self.failures_left = 2

        def jog(
            self,
            x: float = 0,
            y: float = 0,
            z: float = 0,
            feed_rate: float = 2000,
        ) -> None:
            super().jog(x=x, y=y, z=z, feed_rate=feed_rate)
            if self.failures_left:
                self.failures_left -= 1
                raise CommandExecutionError("ALARM:1 hard limit")

    gantry = RetryingGantry()

    result = recover_from_limit_alarm(
        gantry,
        {"x": 0.0, "y": 0.0, "z": 1.0},
        pull_off_mm=5.0,
        feed_rate=900.0,
        output=messages.append,
    )

    assert result.attempts == 3
    assert gantry.calls.count(("reset_and_unlock",)) == 3
    assert gantry.calls.count(("jog", 0.0, 0.0, -5.0, 900.0)) == 3


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

    assert any("Aborting" in m for m in messages)
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
