"""End-to-end integration test for protocol setup and execution."""

from __future__ import annotations

import importlib
import os
import tempfile

import pytest

from gantry.gantry_config import GantryConfig
from protocol_engine.protocol import Protocol, ProtocolContext
from protocol_engine.registry import CommandRegistry
from protocol_engine.setup import setup_protocol
from validation.errors import SetupValidationError


@pytest.fixture(autouse=True)
def _ensure_commands_registered():
    """Ensure protocol commands are registered (may be cleared by other test fixtures)."""
    if not CommandRegistry.instance().command_names:
        import protocol_engine.commands.move
        import protocol_engine.commands.pipette
        import protocol_engine.commands.scan
        importlib.reload(protocol_engine.commands.move)
        importlib.reload(protocol_engine.commands.pipette)
        importlib.reload(protocol_engine.commands.scan)


# ── Full config YAML strings ────────────────────────────────────────────

GANTRY_YAML = """\
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  homing_strategy: standard
  total_z_range: 90.0
  safe_z: 70.0
working_volume:
  x_min: 0.0
  x_max: 300.0
  y_min: 0.0
  y_max: 200.0
  z_min: 0.0
  z_max: 80.0
instruments:
  pipette:
    type: pipette
    vendor: opentrons
    offset_x: 5.0
    offset_y: 0.0
    depth: 3.0
"""

DECK_YAML = """\
labware:
  plate_1:
    type: well_plate
    name: test_96_well
    model_name: test_96_well
    rows: 2
    columns: 3
    length: 50.0
    width: 30.0
    height: 14.0
    calibration:
      a1:
        x: 100.0
        y: 100.0
        z: 15.0
      a2:
        x: 109.0
        y: 100.0
        z: 15.0
    x_offset: 9.0
    y_offset: 9.0
    capacity_ul: 200.0
    working_volume_ul: 150.0
  waste_vial:
    type: vial
    name: waste
    model_name: waste_container
    height: 100.0
    diameter: 50.0
    location:
      x: 250.0
      y: 150.0
      z: 30.0
    capacity_ul: 50000.0
    working_volume_ul: 40000.0
"""

PROTOCOL_YAML = """\
protocol:
  - move:
      instrument: pipette
      position: plate_1.A1
  - move:
      instrument: pipette
      position: waste_vial
"""


def _write_temp_yaml(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestEndToEndSetup:

    def test_full_setup_loads_and_validates_successfully(self):
        paths = [
            _write_temp_yaml(GANTRY_YAML),
            _write_temp_yaml(DECK_YAML),
            _write_temp_yaml(PROTOCOL_YAML),
        ]
        try:
            protocol, context = setup_protocol(*paths)

            assert isinstance(protocol, Protocol)
            assert isinstance(context, ProtocolContext)
            assert isinstance(context.gantry, GantryConfig)
            assert len(protocol) == 2
            assert "pipette" in context.board.instruments
            assert "plate_1" in context.deck
            assert "waste_vial" in context.deck
        finally:
            for p in paths:
                os.unlink(p)

    def test_full_setup_protocol_can_run_with_mock_gantry(self):
        paths = [
            _write_temp_yaml(GANTRY_YAML),
            _write_temp_yaml(DECK_YAML),
            _write_temp_yaml(PROTOCOL_YAML),
        ]
        try:
            protocol, context = setup_protocol(*paths)
            results = protocol.run(context)
            assert len(results) == 2
        finally:
            for p in paths:
                os.unlink(p)

    def test_setup_catches_labware_outside_gantry_bounds(self):
        bad_deck = """\
labware:
  far_vial:
    type: vial
    name: far_away
    model_name: far_vial
    height: 50.0
    diameter: 20.0
    location:
          x: 500.0
          y: 40.0
          z: 20.0
    capacity_ul: 1000.0
    working_volume_ul: 800.0
"""
        paths = [
            _write_temp_yaml(GANTRY_YAML),
            _write_temp_yaml(bad_deck),
            _write_temp_yaml(PROTOCOL_YAML),
        ]
        try:
            with pytest.raises(SetupValidationError) as exc_info:
                setup_protocol(*paths)
            assert any(v.labware_key == "far_vial" for v in exc_info.value.violations)
        finally:
            for p in paths:
                os.unlink(p)

    def test_setup_catches_gantry_position_violation_from_instrument_offset(self):
        # Vial at x=1.0, pipette offset_x=5.0
        # gantry_x = 1.0 - 5.0 = -4.0 < x_min=0.0
        edge_deck = """\
labware:
  edge_vial:
    type: vial
    name: edge
    model_name: edge_vial
    height: 50.0
    diameter: 20.0
    location:
          x: 1.0
          y: 40.0
          z: 20.0
    capacity_ul: 1000.0
    working_volume_ul: 800.0
"""
        paths = [
            _write_temp_yaml(GANTRY_YAML),
            _write_temp_yaml(edge_deck),
            _write_temp_yaml(PROTOCOL_YAML),
        ]
        try:
            with pytest.raises(SetupValidationError) as exc_info:
                setup_protocol(*paths)
            gantry_violations = [v for v in exc_info.value.violations if v.coordinate_type == "gantry"]
            assert len(gantry_violations) >= 1
            assert gantry_violations[0].instrument_name == "pipette"
        finally:
            for p in paths:
                os.unlink(p)

    def test_setup_with_tight_bounds_validates_all_well_positions(self):
        tight_gantry = """\
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  homing_strategy: standard
  total_z_range: 90.0
working_volume:
  x_min: 0.0
  x_max: 50.0
  y_min: 0.0
  y_max: 50.0
  z_min: 0.0
  z_max: 50.0
instruments:
  pipette:
    type: pipette
    vendor: opentrons
    offset_x: 5.0
    offset_y: 0.0
    depth: 3.0
"""
        # plate_1 and waste_vial positions are outside tight positive bounds.
        paths = [
            _write_temp_yaml(tight_gantry),
            _write_temp_yaml(DECK_YAML),
            _write_temp_yaml(PROTOCOL_YAML),
        ]
        try:
            with pytest.raises(SetupValidationError) as exc_info:
                setup_protocol(*paths)
            assert len(exc_info.value.violations) > 0
        finally:
            for p in paths:
                os.unlink(p)
