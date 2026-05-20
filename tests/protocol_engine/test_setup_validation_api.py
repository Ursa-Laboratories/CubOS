"""Tests for the reusable CubOS setup-validation API."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from protocol_engine.setup_validation import run_setup_validation
from protocol_engine.registry import CommandRegistry


GANTRY_YAML = """\
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  homing_strategy: standard
  total_z_range: 90.0
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
    depth: 0.0
"""

DECK_YAML = """\
labware: {}
"""


@pytest.fixture(autouse=True)
def _ensure_commands_registered():
    """Other protocol tests reset the singleton registry; restore real move."""
    if "move" not in CommandRegistry.instance().command_names:
        import importlib
        import protocol_engine.commands.move

        importlib.reload(protocol_engine.commands.move)


def _write(path: Path, content: str) -> Path:
    path.write_text(dedent(content), encoding="utf-8")
    return path


def test_run_setup_validation_passes_with_named_protocol_positions(tmp_path):
    gantry = _write(tmp_path / "gantry.yaml", GANTRY_YAML)
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(
        tmp_path / "protocol.yaml",
        """\
        positions:
          park: [50.0, 50.0, 30.0]
        protocol:
          - move:
              instrument: pipette
              position: park
        """,
    )

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed is True
    assert result.errors == ()
    assert "RESULT: PASS" in result.output
    assert "1 protocol target(s) checked" in result.output


def test_run_setup_validation_reports_named_position_bounds_errors(tmp_path):
    gantry = _write(tmp_path / "gantry.yaml", GANTRY_YAML)
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(
        tmp_path / "protocol.yaml",
        """\
        positions:
          park: [2.0, 50.0, 30.0]
        protocol:
          - move:
              instrument: pipette
              position: park
        """,
    )

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed is False
    assert result.stage == "validation"
    assert any("park.location.target" in error for error in result.errors)
    assert "RESULT: FAIL" in result.output
