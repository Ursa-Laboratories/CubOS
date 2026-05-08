"""Tests for setup_protocol: load all configs, validate, return ready-to-run protocol."""

from __future__ import annotations

import importlib
import os
import tempfile

import pytest

from board.errors import BoardLoaderError
from deck.errors import DeckLoaderError
from gantry.errors import GantryLoaderError
from gantry.gantry_config import GantryConfig
from protocol_engine.errors import ProtocolLoaderError
from protocol_engine.protocol import Protocol, ProtocolContext
from protocol_engine.registry import CommandRegistry
from protocol_engine.setup import run_protocol, setup_protocol
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


# ── YAML templates ──────────────────────────────────────────────────────

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
labware:
  vial_1:
    type: vial
    name: test_vial
    model_name: standard_vial
    height: 66.75
    diameter: 28.0
    location:
      x: 30.0
      y: 40.0
      z: 20.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""

PROTOCOL_YAML = """\
protocol:
  - move:
      instrument: pipette
      position: vial_1
"""


def _gantry_with_instruments(instruments_yaml: str) -> str:
    return GANTRY_YAML.split("instruments:\n", 1)[0] + instruments_yaml


def _write_temp_yaml(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return f.name


class _TempYamlFiles:
    """Context manager that creates temp YAML files and cleans them up."""

    def __init__(
        self,
        gantry: str = GANTRY_YAML,
        deck: str = DECK_YAML,
        protocol: str = PROTOCOL_YAML,
    ):
        self._gantry = gantry
        self._deck = deck
        self._protocol = protocol
        self.paths: list[str] = []

    def __enter__(self):
        self.gantry_path = _write_temp_yaml(self._gantry)
        self.deck_path = _write_temp_yaml(self._deck)
        self.protocol_path = _write_temp_yaml(self._protocol)
        self.paths = [self.gantry_path, self.deck_path, self.protocol_path]
        return self

    def __exit__(self, *args):
        for p in self.paths:
            if os.path.exists(p):
                os.unlink(p)


# ── Tests ────────────────────────────────────────────────────────────────


class TestSetupProtocol:

    def test_setup_returns_protocol_and_context(self):
        with _TempYamlFiles() as f:
            protocol, context = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
            )
            assert isinstance(protocol, Protocol)
            assert isinstance(context, ProtocolContext)

    def test_context_has_board_with_instruments(self):
        with _TempYamlFiles() as f:
            _, context = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
            )
            assert "pipette" in context.board.instruments

    def test_context_has_deck_with_labware(self):
        with _TempYamlFiles() as f:
            _, context = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
            )
            assert "vial_1" in context.deck

    def test_setup_accepts_nested_holder_yaml_positions(self):
        deck_yaml = """\
labware:
  vial_holder:
    type: vial_holder
    name: panda_vial_holder
    location:
      x: 17.1
      y: 132.9
      z: 20.0
    vials:
      vial_1:
        model_name: 20ml_vial
        height: 57.0
        diameter: 28.0
        location:
          x: 17.1
          y: 0.9
        capacity_ul: 20000.0
        working_volume_ul: 12000.0
"""
        protocol_yaml = """\
protocol:
  - move:
      instrument: pipette
      position: vial_holder.vial_1
"""
        with _TempYamlFiles(deck=deck_yaml, protocol=protocol_yaml) as f:
            _, context = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
            )

            assert "vial_holder" in context.deck

    def test_context_has_gantry_config(self):
        with _TempYamlFiles() as f:
            _, context = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
            )
            assert isinstance(context.gantry, GantryConfig)
            assert context.gantry.working_volume.x_min == 0.0

    def test_rejects_negative_space_gantry_config(self):
        legacy_gantry = GANTRY_YAML.replace("  x_min: 0.0\n", "  x_min: -300.0\n")
        with _TempYamlFiles(gantry=legacy_gantry) as f:
            with pytest.raises(ValueError, match="Deck-origin calibration requires"):
                setup_protocol(
                    f.gantry_path, f.deck_path, f.protocol_path,
                )

    def test_protocol_has_expected_steps(self):
        with _TempYamlFiles() as f:
            protocol, _ = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
            )
            assert len(protocol) == 1
            assert protocol.steps[0].command_name == "move"

    def test_raises_on_deck_position_out_of_bounds(self):
        out_of_bounds_deck = """\
labware:
  vial_1:
    type: vial
    name: test_vial
    model_name: standard_vial
    height: 66.75
    diameter: 28.0
    location:
      x: 301.0
      y: 40.0
      z: 20.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""
        with _TempYamlFiles(deck=out_of_bounds_deck) as f:
            with pytest.raises(SetupValidationError) as exc_info:
                setup_protocol(
                    f.gantry_path, f.deck_path, f.protocol_path,
                )
            assert len(exc_info.value.violations) >= 1

    def test_raises_on_gantry_position_out_of_bounds(self):
        # vial at x=2.0, pipette offset_x=5.0 -> gantry_x = 2.0 - 5.0 = -3.0 < x_min=0
        near_edge_deck = """\
labware:
  vial_1:
    type: vial
    name: test_vial
    model_name: standard_vial
    height: 66.75
    diameter: 28.0
    location:
      x: 2.0
      y: 40.0
      z: 20.0
    capacity_ul: 1500.0
    working_volume_ul: 1200.0
"""
        with _TempYamlFiles(deck=near_edge_deck) as f:
            with pytest.raises(SetupValidationError) as exc_info:
                setup_protocol(
                    f.gantry_path, f.deck_path, f.protocol_path,
                )
            assert any(v.coordinate_type == "gantry" for v in exc_info.value.violations)

    def test_raises_on_missing_gantry_file(self):
        with _TempYamlFiles() as f:
            with pytest.raises(GantryLoaderError):
                setup_protocol(
                    "/nonexistent/gantry.yaml", f.deck_path, f.protocol_path,
                )

    def test_raises_on_missing_deck_file(self):
        with _TempYamlFiles() as f:
            with pytest.raises(DeckLoaderError):
                setup_protocol(
                    f.gantry_path, "/nonexistent/deck.yaml", f.protocol_path,
                )

    def test_raises_on_missing_legacy_board_file(self):
        with _TempYamlFiles() as f:
            with pytest.raises(BoardLoaderError):
                setup_protocol(
                    f.gantry_path, f.deck_path, "/nonexistent/board.yaml", f.protocol_path,
                )

    def test_raises_when_gantry_has_no_instruments(self):
        gantry_without_instruments = GANTRY_YAML.split("instruments:\n", 1)[0]
        with _TempYamlFiles(gantry=gantry_without_instruments) as f:
            with pytest.raises(BoardLoaderError, match="instruments"):
                setup_protocol(
                    f.gantry_path, f.deck_path, f.protocol_path,
                )

    def test_raises_on_missing_protocol_file(self):
        with _TempYamlFiles() as f:
            with pytest.raises(ProtocolLoaderError):
                setup_protocol(
                    f.gantry_path, f.deck_path, "/nonexistent/protocol.yaml",
                )

    def test_uses_mock_gantry_by_default(self):
        with _TempYamlFiles() as f:
            _, context = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
            )
            # Board should have a gantry (mock) — verify it exists
            assert context.board.gantry is not None

    def test_mock_mode_swaps_instrument_types(self):
        gantry_yaml = _gantry_with_instruments("""\
instruments:
  pipette:
    type: pipette
    vendor: opentrons
    offset_x: -5.0
    offset_y: 0.0
    depth: 0.0
""")
        with _TempYamlFiles(gantry=gantry_yaml) as f:
            _, context = setup_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
                mock_mode=True,
            )
            from instruments.pipette.driver import Pipette
            assert isinstance(context.board.instruments["pipette"], Pipette)
            assert context.board.instruments["pipette"]._offline is True


class TestRunProtocolLifecycle:

    def test_run_protocol_connects_and_disconnects(self):
        with _TempYamlFiles() as f:
            results = run_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
                mock_mode=True,
            )
            assert isinstance(results, list)

    def test_run_protocol_disconnects_on_failure(self):
        bad_protocol = """\
protocol:
  - move:
      instrument: nonexistent_instrument
      position: vial_1
"""
        with _TempYamlFiles(protocol=bad_protocol) as f:
            with pytest.raises(Exception):
                run_protocol(
                    f.gantry_path, f.deck_path, f.protocol_path,
                    mock_mode=True,
                )

    def test_run_protocol_mock_mode(self):
        gantry_yaml = _gantry_with_instruments("""\
instruments:
  pipette:
    type: pipette
    vendor: opentrons
    offset_x: -5.0
    offset_y: 0.0
    depth: 0.0
""")
        with _TempYamlFiles(gantry=gantry_yaml) as f:
            results = run_protocol(
                f.gantry_path, f.deck_path, f.protocol_path,
                mock_mode=True,
            )
            assert isinstance(results, list)
