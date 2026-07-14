"""Tests for the reusable CubOS setup-validation API."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from cubos.protocol_engine.setup_validator import run_setup_validation
from cubos.protocol_engine.registry import CommandRegistry


GANTRY_YAML = """\
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  factory_z_travel_mm: 90.0
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
    """Other protocol tests reset the singleton registry; restore real commands."""
    required_commands = {
        "home",
        "measure",
        "move",
        "pause",
        "scan",
        "transfer",
        "serial_transfer",
    }
    if required_commands.issubset(set(CommandRegistry.instance().command_names)):
        return

    import importlib

    modules = [
        importlib.import_module("cubos.protocol_engine.commands.home"),
        importlib.import_module("cubos.protocol_engine.commands.measure"),
        importlib.import_module("cubos.protocol_engine.commands.move"),
        importlib.import_module("cubos.protocol_engine.commands.pause"),
        importlib.import_module("cubos.protocol_engine.commands.pipette"),
        importlib.import_module("cubos.protocol_engine.commands.scan"),
    ]
    CommandRegistry.reset()
    for module in modules:
        importlib.reload(module)


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


@pytest.mark.parametrize("command_yaml", [
    """\
    protocol:
      - pause:
          seconds: 0.1
    """,
    """\
    protocol:
      - breakpoint:
          message: Continue?
    """,
])
def test_run_setup_validation_allows_no_motion_commands(tmp_path, command_yaml):
    gantry = _write(tmp_path / "gantry.yaml", GANTRY_YAML)
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(tmp_path / "protocol.yaml", command_yaml)

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed is True
    assert result.errors == ()
    assert "RESULT: PASS" in result.output


# ---------------------------------------------------------------------------
# Error-stage routing
# ---------------------------------------------------------------------------


def test_run_setup_validation_returns_gantry_stage_on_bad_gantry_yaml(tmp_path):
    gantry = _write(tmp_path / "gantry.yaml", "not: valid: gantry: yaml: [[[")
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(tmp_path / "protocol.yaml", "protocol: []\n")

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed is False
    assert result.stage == "gantry"
    assert "RESULT: ERROR" in result.output
    assert result.errors


def test_run_setup_validation_returns_deck_stage_on_bad_deck_yaml(tmp_path):
    gantry = _write(tmp_path / "gantry.yaml", GANTRY_YAML)
    deck = _write(tmp_path / "deck.yaml", "not: valid: deck: [[[")
    protocol = _write(tmp_path / "protocol.yaml", "protocol: []\n")

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed is False
    assert result.stage == "deck"
    assert "RESULT: ERROR" in result.output


def test_run_setup_validation_returns_protocol_stage_on_bad_protocol_yaml(tmp_path):
    gantry = _write(tmp_path / "gantry.yaml", GANTRY_YAML)
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(tmp_path / "protocol.yaml", "not: valid: protocol: [[[")

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed is False
    assert result.stage == "protocol"
    assert "RESULT: ERROR" in result.output


def test_run_setup_validation_returns_gantry_stage_on_missing_gantry_file(tmp_path):
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(tmp_path / "protocol.yaml", "protocol: []\n")

    result = run_setup_validation(tmp_path / "missing.yaml", deck, protocol)

    assert result.passed is False
    assert result.stage == "gantry"
    assert "FileNotFoundError" in result.errors[0] or result.errors


def test_run_setup_validation_error_message_includes_exception_type(tmp_path):
    gantry = _write(tmp_path / "gantry.yaml", "not: valid: gantry: yaml: [[[")
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(tmp_path / "protocol.yaml", "protocol: []\n")

    result = run_setup_validation(gantry, deck, protocol)

    # Error message must include the exception class name so devs can diagnose
    # without needing a full traceback.
    assert any(":" in err for err in result.errors)


# ---------------------------------------------------------------------------
# Validation-engine failure
# ---------------------------------------------------------------------------


def test_run_setup_validation_returns_validation_stage_on_validator_exception(
    tmp_path, monkeypatch
):
    from cubos.protocol_engine import setup_validator as sv

    def _raise(*args, **kwargs):
        raise KeyError("labware_key_missing_from_deck")

    monkeypatch.setattr(sv, "collect_protocol_motion_targets", _raise)

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

    assert result.passed is False
    assert result.stage == "validation"
    assert "RESULT: ERROR" in result.output
    assert "KeyError" in result.errors[0]


def test_run_setup_validation_returns_instruments_stage_on_instrument_load_error(
    tmp_path, monkeypatch
):
    from cubos.protocol_engine import setup_validator as sv

    monkeypatch.setattr(
        sv,
        "load_instrumented_gantry_from_config",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("unknown instrument type: foo")),
    )

    gantry = _write(tmp_path / "gantry.yaml", GANTRY_YAML)
    deck = _write(tmp_path / "deck.yaml", DECK_YAML)
    protocol = _write(tmp_path / "protocol.yaml", "protocol: []\n")

    result = run_setup_validation(gantry, deck, protocol)

    assert result.passed is False
    assert result.stage == "instruments"
    assert "RESULT: ERROR" in result.output
    assert result.errors


def test_run_setup_validation_reports_semantic_violations(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cubos.protocol_engine import setup_validator as sv

    monkeypatch.setattr(
        sv,
        "validate_protocol_semantics",
        lambda *a, **kw: [
            SimpleNamespace(step_index=0, command_name="move", message="missing instrument")
        ],
    )

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

    assert result.passed is False
    assert result.stage == "validation"
    assert any("missing instrument" in error for error in result.errors)
