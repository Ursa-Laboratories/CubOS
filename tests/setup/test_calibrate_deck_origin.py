"""Offline tests for single-instrument calibration helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from gantry.gantry_driver.exceptions import (
    CommandExecutionError,
    StatusReturnError,
)
from setup.calibration.single_instrument_calibration import (
    DeckOriginCalibrationResult,
    run_calibration,
)


def _write_gantry(path: Path, *, x_min: float = 0.0) -> Path:
    path.write_text(
        f"""\
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  homing_strategy: standard
  total_z_range: 100.0
  y_axis_motion: head
  safe_z: 85.0
working_volume:
  x_min: {x_min}
  x_max: 400.0
  y_min: 0.0
  y_max: 300.0
  z_min: 0.0
  z_max: 100.0
""",
        encoding="utf-8",
    )
    return path


class _FakeGantry:
    instance: "_FakeGantry"

    def __init__(self, config: dict):
        self.config = config
        self.calls: list[tuple] = []
        self.coords = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.home_count = 0
        _FakeGantry.instance = self

    def connect(self) -> None:
        self.calls.append(("connect",))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    def home(self) -> None:
        self.calls.append(("home",))
        self.home_count += 1
        if self.home_count == 2:
            self.coords = {"x": 398.5, "y": 299.25, "z": 96.75}

    def clear_g92_offsets(self) -> None:
        self.calls.append(("clear_g92_offsets",))

    def enforce_work_position_reporting(self) -> None:
        self.calls.append(("enforce_work_position_reporting",))

    def activate_work_coordinate_system(self, system: str = "G54") -> None:
        self.calls.append(("activate_work_coordinate_system", system))

    def set_work_coordinates(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
    ) -> None:
        self.calls.append(("set_work_coordinates", x, y, z))
        if x is not None:
            self.coords["x"] = x
        if y is not None:
            self.coords["y"] = y
        if z is not None:
            self.coords["z"] = z

    def get_coordinates(self) -> dict[str, float]:
        self.calls.append(("get_coordinates",))
        return self.coords

    def jog(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        feed_rate: float = 2000,
    ) -> None:
        self.calls.append(("jog", x, y, z, feed_rate))
        self.coords = {
            "x": self.coords["x"] + x,
            "y": self.coords["y"] + y,
            "z": self.coords["z"] + z,
        }

    def jog_cancel(self) -> None:
        self.calls.append(("jog_cancel",))

    def stop(self) -> None:
        self.calls.append(("stop",))

    def unlock(self) -> None:
        self.calls.append(("unlock",))

    def reset_and_unlock(self) -> None:
        self.calls.append(("reset_and_unlock",))

    def set_serial_timeout(self, timeout: float) -> None:
        self.calls.append(("set_serial_timeout", timeout))

    def set_expected_grbl_settings(
        self,
        settings: dict[str, float] | None,
        *,
        source: str = "gantry",
    ) -> None:
        self.calls.append(("set_expected_grbl_settings", settings, source))

    def configure_soft_limits_from_spans(
        self,
        *,
        max_travel_x: float,
        max_travel_y: float,
        max_travel_z: float,
        tolerance_mm: float = 0.001,
    ) -> None:
        self.calls.append(
            (
                "configure_soft_limits_from_spans",
                max_travel_x,
                max_travel_y,
                max_travel_z,
                tolerance_mm,
            )
        )


class _LimitRecoveringFakeGantry(_FakeGantry):
    def __init__(self, config: dict):
        super().__init__(config)
        self.fail_next_jog = True
        self.fail_next_recovery_readback = False

    def jog(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        feed_rate: float = 2000,
    ) -> None:
        if self.fail_next_jog:
            self.fail_next_jog = False
            self.calls.append(("jog", x, y, z, feed_rate))
            raise CommandExecutionError("Alarm in status: <Alarm|WPos:0,0,0|Pn:Y>")
        super().jog(x=x, y=y, z=z, feed_rate=feed_rate)

    def get_coordinates(self) -> dict[str, float]:
        if self.fail_next_recovery_readback:
            self.fail_next_recovery_readback = False
            self.calls.append(("get_coordinates_failed",))
            raise StatusReturnError("WPos readback unavailable")
        return super().get_coordinates()


class _LimitRecoveringNoReadbackFakeGantry(_LimitRecoveringFakeGantry):
    def __init__(self, config: dict):
        super().__init__(config)
        self.fail_next_recovery_readback = True


class _SoftLimitAwareFakeGantry(_FakeGantry):
    def __init__(self, config: dict):
        super().__init__(config)
        self.grbl_settings = {"$20": "1"}

    def read_grbl_settings(self) -> dict[str, str]:
        self.calls.append(("read_grbl_settings",))
        return dict(self.grbl_settings)

    def set_grbl_setting(self, setting: str, value: float | int | bool) -> None:
        self.calls.append(("set_grbl_setting", setting, value))
        self.grbl_settings[setting] = str(value)


class _SoftLimitRejectingFakeGantry(_FakeGantry):
    def __init__(self, config: dict):
        super().__init__(config)
        self.fail_next_jog = True

    def jog(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        feed_rate: float = 2000,
    ) -> None:
        if self.fail_next_jog:
            self.fail_next_jog = False
            self.calls.append(("jog", x, y, z, feed_rate))
            raise CommandExecutionError("Jog failed: error:15")
        super().jog(x=x, y=y, z=z, feed_rate=feed_rate)


class _SoftLimitAwareFailingJogFakeGantry(_SoftLimitAwareFakeGantry):
    def jog(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        feed_rate: float = 2000,
    ) -> None:
        self.calls.append(("jog", x, y, z, feed_rate))
        raise CommandExecutionError("Jog failed: unexpected controller error")


def _key_reader(keys):
    iterator = iter(keys)

    def read():
        return next(iterator)

    return read


def test_run_calibration_sets_xy_then_z_and_measures_home(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    result = run_calibration(
        path,
        output=messages.append,
        gantry_factory=_FakeGantry,
        key_reader=_key_reader(
            [
                ("LEFT", 1),
                ("DOWN", 2),
                ("Z", 3),
                ("\r", 1),
            ]
        ),
        stdin_flusher=lambda: None,
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    assert result.xy_origin_verification == (0.0, 0.0, -3.0)
    assert result.z_reference_verification == (0.0, 0.0, 0.0)
    assert result.reference_verification == (0.0, 0.0, 0.0)
    assert result.z_min_mm == 0.0
    assert result.reachable_z_min_mm == 0.0
    assert result.measured_working_volume == (398.5, 299.25, 96.75)
    assert result.grbl_max_travel == (398.5, 299.25, 96.75)
    assert result.plan.origin_wpos == (0.0, 0.0, 0.0)
    assert _FakeGantry.instance.calls == [
        ("connect",),
        ("set_serial_timeout", 10.0),
        ("home",),
        ("set_serial_timeout", 1.0),
        ("enforce_work_position_reporting",),
        ("activate_work_coordinate_system", "G54"),
        ("clear_g92_offsets",),
        ("jog", -1.0, 0.0, 0.0, 2500.0),
        ("get_coordinates",),
        ("jog", 0.0, -2.0, 0.0, 2500.0),
        ("get_coordinates",),
        ("jog", 0.0, 0.0, -3.0, 2500.0),
        ("get_coordinates",),
        ("get_coordinates",),
        ("set_work_coordinates", 0.0, 0.0, None),
        ("get_coordinates",),
        ("set_work_coordinates", None, None, 0.0),
        ("get_coordinates",),
        ("set_serial_timeout", 10.0),
        ("home",),
        ("set_serial_timeout", 1.0),
        ("get_coordinates",),
        ("configure_soft_limits_from_spans", 398.5, 299.25, 96.75, 0.25),
        ("set_serial_timeout", 0.05),
        ("disconnect",),
    ]
    assert any("WPos Z=0" in message for message in messages)
    assert any("Z reference point after XY origining" in message for message in messages)
    assert any("Measured physical working volume" in message for message in messages)


def test_run_calibration_assigns_ruler_gap_to_lower_reach_z(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    result = run_calibration(
        path,
        output=messages.append,
        gantry_factory=_FakeGantry,
        key_reader=_key_reader(
            [
                ("\r", 1),
            ]
        ),
        stdin_flusher=lambda: None,
        tip_gap_mm=43.0,
        z_reference_mode="ruler-gap",
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    assert result.xy_origin_verification == (0.0, 0.0, 0.0)
    assert result.z_reference_verification == (0.0, 0.0, 43.0)
    assert result.z_min_mm == 43.0
    assert result.reachable_z_min_mm == 43.0
    assert result.grbl_max_travel == (398.5, 299.25, 53.75)
    assert ("set_work_coordinates", 0.0, 0.0, None) in _FakeGantry.instance.calls
    assert ("set_work_coordinates", None, None, 43.0) in _FakeGantry.instance.calls
    assert any("WPos Z=43" in message for message in messages)
    assert any("z_min: 43.000" in message for message in messages)


def test_run_calibration_prints_full_gantry_yaml_with_grbl_settings(tmp_path):
    path = tmp_path / "gantry.yaml"
    path.write_text(
        """\
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  homing_strategy: standard
  total_z_range: 100.0
  y_axis_motion: head
  safe_z: 85.0
working_volume:
  x_min: 0.0
  x_max: 400.0
  y_min: 0.0
  y_max: 300.0
  z_min: 0.0
  z_max: 100.0
grbl_settings:
  dir_invert_mask: 1
  steps_per_mm_x: 400.0
instruments:
  asmi:
    type: asmi
    vendor: vernier
""",
        encoding="utf-8",
    )
    messages: list[str] = []

    result = run_calibration(
        path,
        output=messages.append,
        gantry_factory=_FakeGantry,
        key_reader=_key_reader([("\r", 1)]),
        stdin_flusher=lambda: None,
        tip_gap_mm=24.0,
        z_reference_mode="ruler-gap",
        skip_soft_limit_config=True,
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    output_text = "\n".join(messages)
    assert "Full gantry YAML to copy/paste:" in output_text
    assert "dir_invert_mask: 1" in output_text
    assert "steps_per_mm_x: 400.0" in output_text
    assert "soft_limits: true" in output_text
    assert "homing_enable: true" in output_text
    assert "max_travel_x: 398.5" in output_text
    assert "max_travel_y: 299.25" in output_text
    assert "max_travel_z: 72.75" in output_text
    assert "instruments:" in output_text
    assert _FakeGantry.instance.calls[0] == ("connect",)


def test_run_calibration_can_prompt_and_write_gantry_yaml(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    output_path = tmp_path / "written_gantry.yaml"
    responses = iter([str(output_path), "y"])

    run_calibration(
        path,
        output=lambda message: None,
        input_reader=lambda prompt: next(responses),
        gantry_factory=_FakeGantry,
        key_reader=_key_reader([("\r", 1)]),
        stdin_flusher=lambda: None,
        write_gantry_yaml=True,
        skip_soft_limit_config=True,
    )

    written = output_path.read_text(encoding="utf-8")
    assert "grbl_settings:" in written
    assert "soft_limits: true" in written
    assert "max_travel_z: 96.75" in written


def test_run_calibration_prompts_for_tip_gap_when_omitted(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    prompts: list[str] = []

    def input_reader(prompt: str) -> str:
        prompts.append(prompt)
        return "12.5"

    result = run_calibration(
        path,
        output=lambda message: None,
        input_reader=input_reader,
        gantry_factory=_FakeGantry,
        key_reader=_key_reader([("\r", 1)]),
        stdin_flusher=lambda: None,
        tip_gap_mm=None,
        z_reference_mode="ruler-gap",
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    assert result.xy_origin_verification == (0.0, 0.0, 0.0)
    assert result.z_reference_verification == (0.0, 0.0, 12.5)
    assert prompts == ["Deck-to-TCP gap in mm: "]


def test_run_calibration_prompt_mode_can_ground_z_on_bottom_contact(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    prompts: list[str] = []
    responses = iter(["y"])

    def input_reader(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    result = run_calibration(
        path,
        output=lambda message: None,
        input_reader=input_reader,
        gantry_factory=_FakeGantry,
        key_reader=_key_reader([("\r", 1)]),
        stdin_flusher=lambda: None,
        tip_gap_mm=None,
        z_reference_mode="prompt",
        measure_reachable_z_min=None,
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    assert result.z_reference_mode == "bottom"
    assert result.z_min_mm == 0.0
    assert result.z_reference_verification == (0.0, 0.0, 0.0)
    assert prompts == [
        "Is the TCP touching true deck bottom at the current pose? [y/N]: ",
    ]


def test_run_calibration_prompt_mode_uses_ruler_gap_when_not_touching(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []
    prompts: list[str] = []
    responses = iter(["", "14.5"])

    def input_reader(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    result = run_calibration(
        path,
        output=messages.append,
        input_reader=input_reader,
        gantry_factory=_FakeGantry,
        key_reader=_key_reader(
            [
                ("\r", 1),
            ]
        ),
        stdin_flusher=lambda: None,
        tip_gap_mm=None,
        z_reference_mode="prompt",
        measure_reachable_z_min=None,
        instrument_name="asmi",
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    assert result.z_reference_mode == "ruler-gap"
    assert result.z_min_mm == 14.5
    assert result.z_reference_verification == (0.0, 0.0, 14.5)
    assert result.reachable_z_min_mm == pytest.approx(14.5)
    assert prompts == [
        "Is the TCP touching true deck bottom at the current pose? [y/N]: ",
        "Deck-to-TCP gap in mm: ",
    ]
    assert any("asmi_reachable_z_min: 14.500" in message for message in messages)


def test_run_calibration_deprecated_reach_flag_does_not_add_extra_jog(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    result = run_calibration(
        path,
        output=messages.append,
        gantry_factory=_FakeGantry,
        key_reader=_key_reader(
            [
                ("\r", 1),  # confirm X/Y origin
            ]
        ),
        stdin_flusher=lambda: None,
        tip_gap_mm=43.0,
        z_reference_mode="ruler-gap",
        measure_reachable_z_min=True,
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    assert result.xy_origin_verification == (0.0, 0.0, 0.0)
    assert result.z_reference_verification == (0.0, 0.0, 43.0)
    assert result.reachable_z_min_mm == pytest.approx(43.0)
    assert ("jog", 0.0, 0.0, -10.0, 2500.0) not in _FakeGantry.instance.calls
    assert any("deprecated" in message.lower() for message in messages)
    assert any("reference_tcp_reachable_z_min: 43.000" in message for message in messages)


def test_run_calibration_recovers_from_limit_alarm_during_jog(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    result = run_calibration(
        path,
        output=messages.append,
        gantry_factory=_LimitRecoveringFakeGantry,
        key_reader=_key_reader(
            [
                ("DOWN", 1),
                ("DOWN", 1),
                ("\r", 1),
                ("\r", 1),
            ]
        ),
        stdin_flusher=lambda: None,
        limit_pull_off_mm=2.0,
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    assert (
        ("jog", 0.0, -1.0, 0.0, 2500.0)
        in _LimitRecoveringFakeGantry.instance.calls
    )
    assert ("jog_cancel",) in _LimitRecoveringFakeGantry.instance.calls
    assert ("reset_and_unlock",) in _LimitRecoveringFakeGantry.instance.calls
    assert (
        ("jog", 0.0, 5.0, 0.0, 2500.0)
        in _LimitRecoveringFakeGantry.instance.calls
    )
    assert any("Limit alarm detected" in message for message in messages)


def test_run_calibration_temporarily_disables_stale_soft_limits(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    result = run_calibration(
        path,
        output=messages.append,
        gantry_factory=_SoftLimitAwareFakeGantry,
        key_reader=_key_reader([("\r", 1)]),
        stdin_flusher=lambda: None,
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    calls = _SoftLimitAwareFakeGantry.instance.calls
    disable_call = ("set_grbl_setting", "$20", 0)
    restore_call = ("set_grbl_setting", "$20", 1)
    assert disable_call in calls
    assert restore_call in calls
    assert calls.index(disable_call) < calls.index(restore_call)
    assert calls.index(restore_call) < calls.index(
        ("set_work_coordinates", 0.0, 0.0, None)
    )
    assert any("Temporarily disabling GRBL soft limits" in m for m in messages)
    assert any("Restoring GRBL soft limits" in m for m in messages)


def test_run_calibration_continues_after_error_15_jog_rejection(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    result = run_calibration(
        path,
        output=messages.append,
        gantry_factory=_SoftLimitRejectingFakeGantry,
        key_reader=_key_reader([("LEFT", 1), ("\r", 1)]),
        stdin_flusher=lambda: None,
    )

    assert isinstance(result, DeckOriginCalibrationResult)
    calls = _SoftLimitRejectingFakeGantry.instance.calls
    assert ("jog", -1.0, 0.0, 0.0, 2500.0) in calls
    assert ("jog_cancel",) not in calls
    assert ("unlock",) not in calls
    assert any("target exceeds the current soft-limit travel" in m for m in messages)


def test_run_calibration_restores_soft_limits_when_jog_aborts(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    with pytest.raises(CommandExecutionError):
        run_calibration(
            path,
            output=messages.append,
            gantry_factory=_SoftLimitAwareFailingJogFakeGantry,
            key_reader=_key_reader([("LEFT", 1)]),
            stdin_flusher=lambda: None,
        )

    calls = _SoftLimitAwareFailingJogFakeGantry.instance.calls
    assert ("set_grbl_setting", "$20", 0) in calls
    assert ("set_grbl_setting", "$20", 1) in calls
    assert calls.index(("set_grbl_setting", "$20", 0)) < calls.index(
        ("set_grbl_setting", "$20", 1)
    )
    assert ("disconnect",) in calls


def test_run_calibration_aborts_when_recovery_readback_is_unavailable(tmp_path):
    """Recovery readback failure must abort calibration: silently continuing
    would let the operator zero WPos at an unknown physical pose."""
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    with pytest.raises(StatusReturnError):
        run_calibration(
            path,
            output=messages.append,
            gantry_factory=_LimitRecoveringNoReadbackFakeGantry,
            key_reader=_key_reader(
                [
                    ("DOWN", 1),
                    ("DOWN", 1),
                    ("\r", 1),
                    ("\r", 1),
                ]
            ),
            stdin_flusher=lambda: None,
            limit_pull_off_mm=2.0,
        )

    assert ("get_coordinates_failed",) in (
        _LimitRecoveringNoReadbackFakeGantry.instance.calls
    )
    assert any("Pulled off the limit switch" in message for message in messages)


def test_dry_run_prints_commands_without_connecting(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    def fail_factory(**kwargs):
        raise AssertionError("dry run should not construct a gantry")

    run_calibration(
        path,
        dry_run=True,
        output=messages.append,
        gantry_factory=fail_factory,
    )

    assert "  $H" in messages
    assert "  $10=0" in messages
    assert "  G90" in messages
    assert "  G54" in messages
    assert "  G92.1" in messages
    assert "  <interactive jog to front-left XY origin/lower reach point>" in messages
    assert "  G10 L20 P1 X0 Y0" in messages
    assert "  <confirm true deck-bottom contact>" in messages
    assert "  G10 L20 P1 Z0" in messages
    assert "  $20=0" in messages
    assert "  $130=<x_span_mm>" in messages
    assert "  $131=<y_span_mm>" in messages
    assert "  $132=<z_span_mm>" in messages
    assert "  $22=1" in messages
    assert "  $20=1" in messages
    assert "No configured max travel values will be trusted as measured volume." in messages


def test_dry_run_prints_ruler_gap_step(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    run_calibration(
        path,
        dry_run=True,
        output=messages.append,
        z_reference_mode="ruler-gap",
        tip_gap_mm=5.0,
    )

    assert "  <confirm bottom contact or enter ruler-measured TCP gap>" in messages
    assert "  G10 L20 P1 Z5" in messages


def test_dry_run_prints_bottom_reference_step(tmp_path):
    path = _write_gantry(tmp_path / "gantry.yaml")
    messages: list[str] = []

    run_calibration(
        path,
        dry_run=True,
        output=messages.append,
        z_reference_mode="bottom",
    )

    assert "  <confirm true deck-bottom contact>" in messages
    assert "  G10 L20 P1 Z0" in messages


def test_rejects_legacy_negative_space_config(tmp_path):
    path = _write_gantry(tmp_path / "legacy.yaml", x_min=-400.0)

    with pytest.raises(ValueError, match="Deck-origin calibration requires"):
        run_calibration(path, dry_run=True)
