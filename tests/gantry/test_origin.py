"""Tests for gantry deck-origin calibration helpers."""

from __future__ import annotations

import pytest

from gantry.gantry_config import GantryConfig, GantryType, HomingStrategy, WorkingVolume
from gantry.origin import (
    DeckOriginCalibrationPlan,
    build_deck_origin_calibration_plan,
    format_gcode_number,
    format_set_work_position_command,
    validate_deck_origin_minima,
)


def _deck_origin_config(
    *,
    x_min: float = 0.0,
    y_min: float = 0.0,
    z_min: float = 0.0,
    x_max: float = 300.0,
    y_max: float = 200.0,
    z_max: float = 80.0,
) -> GantryConfig:
    return GantryConfig(
        serial_port="/dev/null",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=z_max,
        working_volume=WorkingVolume(
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            z_min=z_min,
            z_max=z_max,
        ),
    )


class TestFormatGcodeNumber:

    def test_strips_trailing_zeros(self):
        assert format_gcode_number(1.250000) == "1.25"

    def test_strips_trailing_decimal_point(self):
        assert format_gcode_number(7.0) == "7"

    def test_collapses_negative_zero(self):
        assert format_gcode_number(-0.0) == "0"

    def test_preserves_negative_values(self):
        assert format_gcode_number(-12.5) == "-12.5"

    def test_rounds_to_six_decimals(self):
        assert format_gcode_number(0.1234567) == "0.123457"

    def test_handles_integer_input(self):
        assert format_gcode_number(0) == "0"


class TestFormatSetWorkPositionCommand:

    def test_all_axes(self):
        cmd = format_set_work_position_command(x=10.0, y=20.0, z=30.0)
        assert cmd == "G10 L20 P1 X10 Y20 Z30"

    def test_x_only(self):
        assert format_set_work_position_command(x=5.5) == "G10 L20 P1 X5.5"

    def test_y_only(self):
        assert format_set_work_position_command(y=2.0) == "G10 L20 P1 Y2"

    def test_z_only(self):
        assert format_set_work_position_command(z=-1.25) == "G10 L20 P1 Z-1.25"

    def test_x_and_z_skips_y(self):
        cmd = format_set_work_position_command(x=1.0, z=2.0)
        assert cmd == "G10 L20 P1 X1 Z2"

    def test_no_axes_raises(self):
        with pytest.raises(ValueError, match="At least one axis"):
            format_set_work_position_command()


class TestValidateDeckOriginMinima:

    def test_valid_zero_minima(self):
        validate_deck_origin_minima(_deck_origin_config())

    def test_z_min_at_negative_tolerance(self):
        validate_deck_origin_minima(_deck_origin_config(z_min=-1e-12))

    def test_rejects_nonzero_x_min(self):
        with pytest.raises(ValueError, match="x_min"):
            validate_deck_origin_minima(_deck_origin_config(x_min=0.5))

    def test_rejects_nonzero_y_min(self):
        with pytest.raises(ValueError, match="y_min"):
            validate_deck_origin_minima(_deck_origin_config(y_min=-0.5))

    def test_rejects_both_x_and_y_min(self):
        with pytest.raises(ValueError) as info:
            validate_deck_origin_minima(_deck_origin_config(x_min=0.1, y_min=0.2))
        assert "x_min" in str(info.value)
        assert "y_min" in str(info.value)

    def test_rejects_negative_z_min(self):
        with pytest.raises(ValueError, match="z_min"):
            validate_deck_origin_minima(_deck_origin_config(z_min=-1.0))


class TestBuildDeckOriginCalibrationPlan:

    def test_origin_wpos_is_zero(self):
        plan = build_deck_origin_calibration_plan(_deck_origin_config())
        assert plan.origin_wpos == (0.0, 0.0, 0.0)

    def test_returns_plan_instance(self):
        plan = build_deck_origin_calibration_plan(_deck_origin_config())
        assert isinstance(plan, DeckOriginCalibrationPlan)

    def test_rejects_non_deck_origin_config(self):
        with pytest.raises(ValueError):
            build_deck_origin_calibration_plan(_deck_origin_config(x_min=10.0))

    def test_command_sequence_starts_with_home_and_disables_soft_limits(self):
        plan = build_deck_origin_calibration_plan(_deck_origin_config())
        assert plan.commands[0] == "$H"
        assert "$10=0" in plan.commands
        assert plan.commands.index("$10=0") < plan.commands.index("G54")

    def test_command_sequence_pins_g92_clear_before_origin_assignment(self):
        plan = build_deck_origin_calibration_plan(_deck_origin_config())
        commands = list(plan.commands)
        assert "G92.1" in commands
        assert "G10 L20 P1 X0 Y0" in commands
        assert commands.index("G92.1") < commands.index("G10 L20 P1 X0 Y0")

    def test_command_sequence_disables_soft_limits_before_writing_max_travel(self):
        plan = build_deck_origin_calibration_plan(_deck_origin_config())
        commands = list(plan.commands)
        idx_disable = commands.index("$20=0")
        idx_x = commands.index("$130=<x_span_mm>")
        idx_y = commands.index("$131=<y_span_mm>")
        idx_z = commands.index("$132=<z_span_mm>")
        idx_homing = commands.index("$22=1")
        idx_enable = commands.index("$20=1")
        assert idx_disable < idx_x < idx_y < idx_z < idx_homing < idx_enable

    def test_command_sequence_re_homes_after_soft_limit_reenable(self):
        plan = build_deck_origin_calibration_plan(_deck_origin_config())
        commands = list(plan.commands)
        idx_enable = commands.index("$20=1")
        rehome_after = commands.index("$H", idx_enable)
        assert rehome_after > idx_enable
        assert commands[-1] == "?"

    def test_command_sequence_assigns_max_corner_wpos_after_rehome(self):
        plan = build_deck_origin_calibration_plan(_deck_origin_config())
        commands = list(plan.commands)
        max_corner = "G10 L20 P1 X<x_max_mm> Y<y_max_mm> Z<z_max_mm>"
        assert max_corner in commands
        idx_enable = commands.index("$20=1")
        assert commands.index(max_corner) > idx_enable
