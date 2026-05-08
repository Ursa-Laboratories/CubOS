"""Rail-guard validation-flow checks for temporary multi-instrument configs."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from setup.validate_setup import run_validation


ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"


def test_validate_setup_home_over_rail_then_low_travel_fails(tmp_path):
    gantry_path = tmp_path / "mock_sterling_two_instrument_rail.yaml"
    protocol_path = tmp_path / "mock_sterling_two_instrument_rail_fail.yaml"
    gantry_path.write_text(
        dedent(
            """\
            serial_port: /dev/ttyUSB0
            gantry_type: cub_xl

            cnc:
              homing_strategy: standard
              total_z_range: 130.0
              y_axis_motion: head
              safe_z: 110.0

            working_volume:
              x_min: 0.0
              x_max: 400.0
              y_min: 0.0
              y_max: 300.0
              z_min: 0.0
              z_max: 130.0

            grbl_settings:
              status_report: 0
              homing_enable: true
              homing_dir_mask: 0
              max_travel_x: 400.0
              max_travel_y: 300.0
              max_travel_z: 130.0

            instruments:
              asmi:
                type: asmi
                vendor: vernier
                offline: true
                offset_x: 0.0
                offset_y: 0.0
                depth: 0.0
                sensor_channels: [1]

              pipette:
                type: pipette
                vendor: opentrons
                offline: true
                port: ""
                pipette_model: p300_single_gen2
                offset_x: 100.0
                offset_y: 0.0
                depth: 0.0
            """
        ),
        encoding="utf-8",
    )
    protocol_path.write_text(
        dedent(
            """\
            positions:
              left_of_rail_high: [460.0, 150.0, 120.0]

            protocol:
              - home:

              - move:
                  instrument: pipette
                  position: left_of_rail_high
                  travel_z: 80.0
            """
        ),
        encoding="utf-8",
    )

    result = run_validation(
        gantry_path,
        CONFIGS / "deck/sterling_deck.yaml",
        protocol_path,
    )

    assert result.passed is False
    assert "home pose" not in result.output
    assert "Cub XL right X-max rail" in result.output
    assert "travel_z lift/lower" in result.output
