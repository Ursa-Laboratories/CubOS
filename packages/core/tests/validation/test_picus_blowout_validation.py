"""Validation follows the Picus retract-before-home protocol lifecycle."""

from types import SimpleNamespace

import pytest

from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.well_plate import WellPlate
from cubos.gantry.gantry_config import GantryConfig, GantryType, WorkingVolume
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette
from cubos.protocol_engine.protocol import Protocol, ProtocolStep
from cubos.validation import protocol_semantics as semantics


def _setup(*, safe_z=70.0, instrument=None):
    instrument = instrument or SartoriusPicus2Pipette(
        name="pipette", depth=10.0, offline=True,
    )
    config = GantryConfig(
        serial_port="/dev/null", gantry_type=GantryType.CUB_XL,
        factory_z_travel_mm=120.0, safe_z=safe_z,
        working_volume=WorkingVolume(
            x_min=0, x_max=540, y_min=0, y_max=300, z_min=0, z_max=120,
        ),
    )
    gantry = InstrumentedGantry(
        SimpleNamespace(config={"working_volume": {"z_max": 120.0}}),
        {"pipette": instrument}, safe_z=config.resolved_safe_z,
    )
    labware = {
        name: Vial(
            name=name, location=Coordinate3D(x=x, y=y, z=20),
            capacity_ul=5000, working_volume_ul=4000,
        )
        for name, x, y in (("source", 10, 20), ("destination", 40, 50), ("waste", 60, 80))
    }
    labware["plate"] = WellPlate(
        name="plate", model_name="test", rows=1, columns=2,
        length=100, width=50, height=20,
        capacity_ul=200, working_volume_ul=150,
        wells={
            "A1": Coordinate3D(x=80, y=60, z=20),
            "A2": Coordinate3D(x=90, y=60, z=20),
        },
    )
    return gantry, Deck(labware), config


def _validate(command, args, poses, **setup_options):
    gantry, deck, config = _setup(**setup_options)
    return semantics._validate_pipette_blowout_retracts(
        step_index=0, command_name=command, args=args,
        instrumented_gantry=gantry, deck=deck, gantry=config,
        current_poses=poses, tip_extension=20.0,
    )


@pytest.mark.parametrize(
    "command,args,expected",
    [
        ("blowout", {"position": "destination", "height": -5.0,
                     "x_offset_mm": 3.0, "y_offset_mm": -4.0}, (43, 46, 70)),
        ("transfer", {"destination": "destination", "destination_height": -5.0,
                      "destination_x_offset_mm": 3.0,
                      "destination_y_offset_mm": -4.0}, (43, 46, 70)),
        ("multi_dispense", {"destinations": ["destination", "waste"],
                            "destination_height": -5.0}, (60, 80, 70)),
        ("serial_transfer", {"plate": "plate", "axis": "A",
                             "destination_x_offset_mm": 3.0,
                             "destination_y_offset_mm": -4.0}, (93, 56, 70)),
        ("rinse_well", {"well": "destination", "waste": "waste"}, (60, 80, 70)),
        ("flush_pipette", {"source": "source", "waste": "waste"}, (60, 80, 70)),
        ("purge_pipette", {"source": "source", "waste": "waste"}, (60, 80, 70)),
        ("clear_well", {"well": "destination", "waste": "waste"}, (60, 80, 70)),
    ],
)
def test_final_pose_matches_successful_retract(command, args, expected):
    poses = {"pipette": (1, 2, 3)}
    assert _validate(command, args, poses) == []
    assert poses["pipette"] == expected


@pytest.mark.parametrize("safe_z,height", [(20.0, -5.0), (15.0, -5.0), (70.0, 50.0)])
@pytest.mark.parametrize("command", ["blowout", "transfer", "multi_dispense"])
def test_clearance_must_exceed_surface_and_action(safe_z, height, command):
    args = (
        {"position": "destination", "height": height}
        if command == "blowout"
        else {"destination": "destination", "destination_height": height}
    )
    if command == "multi_dispense":
        args = {"destinations": ["destination"], "destination_height": height}
    violations = _validate(command, args, {}, safe_z=safe_z)
    assert any("requires safe_z above both" in str(v) for v in violations)


def test_empty_multi_dispense_has_no_blowout_retraction():
    poses = {"pipette": (1, 2, 3)}
    assert _validate("multi_dispense", {"destinations": []}, poses) == []
    assert poses["pipette"] == (1, 2, 3)


@pytest.mark.parametrize("command", ["rinse_well", "flush_pipette", "purge_pipette", "clear_well"])
def test_unknown_automatic_waste_invalidates_previous_pose(command):
    poses = {"pipette": (1, 2, 3), "camera": (10, 20, 30)}
    assert _validate(command, {"well": "destination"}, poses) == []
    assert poses == {"camera": (10, 20, 30)}


@pytest.mark.parametrize("vendor", ["picus_legacy", "opentrons"])
def test_existing_vendor_behavior_does_not_add_retracts(vendor):
    instrument = (
        SartoriusPicus2Pipette(name="pipette", offline=True, blowout_go_home=True)
        if vendor == "picus_legacy"
        else OpentronsPipette(name="pipette", offline=True)
    )
    poses = {"pipette": (40, 50, 15)}
    assert _validate(
        "blowout", {"position": "destination", "height": -5.0}, poses,
        safe_z=20.0, instrument=instrument,
    ) == []
    assert poses["pipette"] == (40, 50, 15)


@pytest.mark.parametrize(
    "command,args,expected",
    [
        ("transfer", {"destination": "destination", "destination_height": None,
                      "liquid_class": None}, (40, 50, 70)),
        ("flush_pipette", {"waste": "waste", "waste_height": None}, (60, 80, 70)),
        ("rinse_well", {"well": "destination", "well_height": None,
                        "waste": "waste", "waste_height": None}, (60, 80, 70)),
    ],
)
def test_optional_null_heights_still_validate_and_track_retraction(command, args, expected):
    poses = {"pipette": (1, 2, 3)}
    assert _validate(command, args, poses) == []
    assert poses["pipette"] == expected
    assert any("requires safe_z above both" in str(v)
               for v in _validate(command, args, {}, safe_z=20.0))


@pytest.mark.parametrize("command,args,expected_pose", [
    ("blowout", {"position": "destination", "height": -5.0}, (40, 50, 70)),
    ("multi_dispense", {"source": "source", "destinations": ["destination", "waste"],
                        "volumes": [50.0, 50.0], "destination_height": -5.0}, (60, 80, 70)),
])
def test_public_validation_supplies_retracted_pose_to_next_move(monkeypatch, command, args, expected_pose):
    gantry, deck, config = _setup()
    protocol = Protocol([
        ProtocolStep(index=0, command_name=command, handler=lambda **kwargs: None, args=args),
        ProtocolStep(index=1, command_name="move", handler=lambda **kwargs: None,
                     args={"instrument": "pipette", "position": [100, 100, 70],
                           "travel_z": 70.0}),
    ])
    seen = []
    validate_transit = semantics._validate_known_transit

    def record_transit(**kwargs):
        if kwargs["step_index"] == 1:
            seen.append(kwargs["current"])
        return validate_transit(**kwargs)

    monkeypatch.setattr(semantics, "_validate_known_transit", record_transit)
    violations = semantics.validate_protocol_semantics(protocol, gantry, deck, config)
    assert all("attached pipette tip" in str(v) for v in violations)
    assert seen == [expected_pose]


@pytest.mark.parametrize("command,args", [
    ("transfer", {"source": "source", "destination": "destination",
                  "volume_ul": 50.0, "destination_height": -5.0}),
    ("multi_dispense", {"source": "source", "destinations": ["destination", "waste"],
                        "volumes": [50.0, 50.0], "destination_height": -5.0}),
])
def test_public_validation_reports_blowout_clearance_error(command, args):
    gantry, deck, config = _setup(safe_z=20.0)
    protocol = Protocol([
        ProtocolStep(index=0, command_name=command, handler=lambda **kwargs: None, args=args),
    ])
    violations = semantics.validate_protocol_semantics(protocol, gantry, deck, config)
    assert any("requires safe_z above both" in str(v) for v in violations)
