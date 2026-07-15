"""Tests for offline (static) protocol fluid-volume validation."""

from __future__ import annotations

from textwrap import dedent

import pytest

from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate
from cubos.instruments.pipette.models import PIPETTE_MODELS
from cubos.protocol_engine.builder import ProtocolBuilder
from cubos.validation.fluid_volumes import validate_protocol_fluid_volumes

P300 = PIPETTE_MODELS["p300_single_gen2"]


def _deck() -> Deck:
    source = Vial(
        name="source",
        height=100.0,
        diameter=20.0,
        location=Coordinate3D(x=5.0, y=5.0, z=50.0),
        capacity_ul=5000.0,
        working_volume_ul=4500.0,
        dead_volume_ul=100.0,
    )
    dest = Vial(
        name="dest",
        height=80.0,
        diameter=25.0,
        location=Coordinate3D(x=40.0, y=5.0, z=45.0),
        capacity_ul=2000.0,
        working_volume_ul=1500.0,
    )
    plate = WellPlate(
        name="plate",
        model_name="test",
        rows=1,
        columns=2,
        wells={
            "A1": Coordinate3D(x=70.0, y=20.0, z=15.0),
            "A2": Coordinate3D(x=79.0, y=20.0, z=15.0),
        },
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )
    return Deck({"source": source, "dest": dest, "plate": plate})


def _protocol(*commands):
    builder = ProtocolBuilder()
    for name, args in commands:
        builder.add_command(name, **args)
    return builder.build()


SEED = {"source": {"volume_ul": 1000.0, "composition": {"water": 1000.0}}}


class TestValidateProtocolFluidVolumes:

    def test_valid_protocol_produces_no_violations(self):
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": 100.0}),
        )
        assert validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        ) == []

    @pytest.mark.parametrize(
        ("volume", "match"),
        [
            (0.0, "> 0"),
            (-10.0, "> 0"),
            (P300.min_volume - 1.0, "minimum"),
        ],
        ids=["zero", "negative", "below-model-min"],
    )
    def test_invalid_volume_for_model_reported(self, volume, match):
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": volume}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert match in violations[0].message

    def test_source_dead_volume_floor_enforced(self):
        # 1000 seeded - 100 dead volume = 900 available; ask for 950.
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": 950.0}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert "dead-volume" in violations[0].message

    def test_destination_working_volume_overflow_enforced(self):
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "plate.A1",
                          "volume_ul": 180.0}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert "working volume" in violations[0].message

    def test_sequential_volume_accounting_across_steps(self):
        # Each step is fine in isolation; the pair drains the source below
        # its dead-volume floor on the second step.
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": 600.0}),
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": 350.0}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert violations[0].step_index == 1
        assert "dead-volume" in violations[0].message

    def test_destination_fill_accumulates_across_steps(self):
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "plate.A1",
                          "volume_ul": 100.0}),
            ("transfer", {"source": "source", "destination": "plate.A1",
                          "volume_ul": 100.0}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert violations[0].step_index == 1
        assert "working volume" in violations[0].message

    def test_unseeded_source_starts_empty(self):
        protocol = _protocol(
            ("transfer", {"source": "dest", "destination": "plate.A1",
                          "volume_ul": 50.0}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert "only 0" in violations[0].message

    def test_serial_transfer_wells_validated_individually(self):
        protocol = _protocol(
            ("serial_transfer", {"source": "source", "plate": "plate",
                                 "axis": "A", "volumes": [100.0, 180.0]}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert "plate.A2" in violations[0].message
        assert "working volume" in violations[0].message

    def test_mix_needs_enough_present_volume(self):
        protocol = _protocol(
            ("mix", {"position": "plate.A1", "volume_ul": 50.0}),
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        )
        assert len(violations) == 1
        assert violations[0].command_name == "mix"

    def test_split_volume_above_capacity_is_legal_statically(self):
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": 600.0}),
        )
        assert validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=P300,
        ) == []

    def test_without_pipette_config_volume_bounds_skipped_but_state_checked(self):
        protocol = _protocol(
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": 5.0}),   # below P300 min: not checked
            ("transfer", {"source": "source", "destination": "dest",
                          "volume_ul": 950.0}),  # crosses dead-volume floor
        )
        violations = validate_protocol_fluid_volumes(
            protocol, _deck(), SEED, pipette_config=None,
        )
        assert len(violations) == 1
        assert "dead-volume" in violations[0].message


# ─── run_setup_validation integration ────────────────────────────────────────


VALIDATOR_GANTRY_YAML = """\
serial_port: /dev/ttyUSB0
gantry_type: cub_xl
cnc:
  factory_z_travel_mm: 90.0
  safe_z: 50.0
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
    pipette_model: p300_single_gen2
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
"""

VALIDATOR_DECK_YAML = """\
labware:
  source:
    type: vial
    name: source
    height: 40.0
    diameter: 20.0
    location: {x: 50.0, y: 50.0, z: 45.0}
    capacity_ul: 5000.0
    working_volume_ul: 4500.0
    dead_volume_ul: 100.0
  dest:
    type: vial
    name: dest
    height: 40.0
    diameter: 25.0
    location: {x: 100.0, y: 50.0, z: 45.0}
    capacity_ul: 2000.0
    working_volume_ul: 1500.0
  tips:
    type: tip_rack
    name: tips
    rows: 1
    columns: 1
    pickup_z: 45.0
    tip_length: 30.0
    calibration:
      a1: {x: 150.0, y: 50.0, z: 45.0}
      a2: {x: 159.0, y: 50.0, z: 45.0}
    x_offset: 9.0
    y_offset: 9.0
"""

VALIDATOR_PROTOCOL_YAML = """\
protocol:
  - pick_up_tip:
      position: tips.A1
  - transfer:
      source: source
      destination: dest
      volume_ul: {volume}
"""

VALIDATOR_FLUIDS_YAML = """\
fluids:
  source:
    volume_ul: 1000.0
"""


class TestRunSetupValidationWithInitialFluids:

    def _run(self, tmp_path, volume, with_fluids=True):
        from cubos.protocol_engine.setup_validator import run_setup_validation

        gantry = tmp_path / "gantry.yaml"
        deck = tmp_path / "deck.yaml"
        protocol = tmp_path / "protocol.yaml"
        fluids = tmp_path / "fluids.yaml"
        gantry.write_text(dedent(VALIDATOR_GANTRY_YAML), encoding="utf-8")
        deck.write_text(dedent(VALIDATOR_DECK_YAML), encoding="utf-8")
        protocol.write_text(
            dedent(VALIDATOR_PROTOCOL_YAML.format(volume=volume)),
            encoding="utf-8",
        )
        fluids.write_text(dedent(VALIDATOR_FLUIDS_YAML), encoding="utf-8")
        return run_setup_validation(
            gantry, deck, protocol,
            initial_fluids_path=fluids if with_fluids else None,
        )

    def test_passes_with_satisfiable_volumes(self, tmp_path):
        result = self._run(tmp_path, volume=600.0)
        assert result.passed, result.output
        assert "Validating protocol fluid volumes" in result.output

    def test_fails_when_source_would_cross_dead_volume(self, tmp_path):
        result = self._run(tmp_path, volume=950.0)
        assert not result.passed
        assert any("dead-volume" in error for error in result.errors)

    def test_fails_on_model_min_violation(self, tmp_path):
        result = self._run(tmp_path, volume=19.0)
        assert not result.passed
        assert any("minimum" in error for error in result.errors)

    def test_fluid_check_skipped_without_initial_fluids(self, tmp_path):
        result = self._run(tmp_path, volume=950.0, with_fluids=False)
        assert result.passed, result.output
        assert "Validating protocol fluid volumes" not in result.output
