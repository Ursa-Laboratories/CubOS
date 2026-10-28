"""Machine-structure collision validation for protocol motion."""

from __future__ import annotations

from unittest.mock import MagicMock

from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.well_plate import WellPlate
from cubos.gantry.gantry_config import (
    GantryConfig,
    GantryType,
    WorkingVolume,
)
from cubos.protocol_engine.protocol import Protocol, ProtocolStep
from cubos.validation.protocol_semantics import validate_protocol_semantics


def _gantry(
    *,
    gantry_type: GantryType = GantryType.CUB_XL,
    x_max: float = 600.0,
    z_max: float = 160.0,
    safe_z: float | None = None,
) -> GantryConfig:
    return GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=gantry_type,
        factory_z_travel_mm=z_max,
        working_volume=WorkingVolume(
            x_min=0.0,
            x_max=x_max,
            y_min=0.0,
            y_max=300.0,
            z_min=0.0,
            z_max=z_max,
        ),
        safe_z=safe_z,
    )


def _instrument(*, name: str = "asmi", offset_x: float = 0.0):
    instr = MagicMock()
    instr.name = name
    instr.offset_x = offset_x
    instr.offset_y = 0.0
    instr.depth = 0.0
    return instr


def _board() -> InstrumentedGantry:
    return InstrumentedGantry(
        controller=MagicMock(),
        instruments={"asmi": _instrument()},
    )


def _deck(*, well_z: float = 40.0) -> Deck:
    return Deck({
        "plate": WellPlate(
            name="plate",
            model_name="test_plate",
            length=127.71,
            width=85.43,
            height=14.10,
            rows=1,
            columns=1,
            wells={"A1": Coordinate3D(x=500.0, y=150.0, z=well_z)},
            capacity_ul=200.0,
            working_volume_ul=150.0,
        )
    })


def _protocol(*steps: ProtocolStep) -> Protocol:
    return Protocol(list(steps))


def _move_step(
    index: int,
    *,
    position,
    instrument: str = "asmi",
    travel_z: float | None = None,
) -> ProtocolStep:
    args = {"instrument": instrument, "position": position}
    if travel_z is not None:
        args["travel_z"] = travel_z
    return ProtocolStep(
        index=index,
        command_name="move",
        handler=lambda *a, **k: None,
        args=args,
    )


def _home_step(index: int) -> ProtocolStep:
    return ProtocolStep(
        index=index,
        command_name="home",
        handler=lambda *a, **k: None,
        args={},
    )


def test_cub_xl_low_pose_inside_right_rail_fails():
    protocol = _protocol(_move_step(0, position=(500.0, 150.0, 50.0)))

    violations = validate_protocol_semantics(
        protocol, _board(), _deck(), _gantry(),
    )

    assert any("Cub XL right X-max rail" in v.message for v in violations), violations


def test_cub_xl_high_pose_inside_right_rail_xy_passes():
    protocol = _protocol(_move_step(0, position=(500.0, 150.0, 81.0)))

    assert validate_protocol_semantics(
        protocol, _board(), _deck(), _gantry(),
    ) == []


def test_cub_type_does_not_apply_cub_xl_right_rail():
    protocol = _protocol(_move_step(0, position=(500.0, 150.0, 50.0)))

    assert validate_protocol_semantics(
        protocol,
        _board(),
        _deck(),
        _gantry(gantry_type=GantryType.CUB),
    ) == []


def test_cub_xl_travel_segment_crossing_right_rail_at_low_z_fails():
    protocol = _protocol(
        _move_step(0, position=(400.0, 150.0, 120.0)),
        _move_step(1, position=(560.0, 150.0, 120.0), travel_z=50.0),
    )

    violations = validate_protocol_semantics(
        protocol, _board(), _deck(), _gantry(),
    )

    assert any(
        "travel segment" in v.message and "Cub XL right X-max rail" in v.message
        for v in violations
    ), violations


def test_home_over_rail_passes_but_lowering_while_over_rail_fails():
    gantry = _gantry(x_max=400.0, z_max=130.0)
    instrumented_gantry = InstrumentedGantry(
        controller=MagicMock(),
        instruments={
            "asmi": _instrument(name="asmi"),
            "pipette": _instrument(name="pipette", offset_x=100.0),
        },
    )
    protocol = _protocol(
        _home_step(0),
        _move_step(
            1,
            instrument="pipette",
            position=(460.0, 150.0, 120.0),
            travel_z=80.0,
        ),
    )

    violations = validate_protocol_semantics(protocol, instrumented_gantry, _deck(), gantry)

    messages = [violation.message for violation in violations]
    assert not any("home pose" in message for message in messages), messages
    assert any("travel_z lift/lower" in message for message in messages), messages
    assert any("Cub XL right X-max rail" in message for message in messages), messages


def test_home_over_rail_at_rail_height_fails():
    gantry = _gantry(x_max=400.0, z_max=80.0)
    instrumented_gantry = InstrumentedGantry(
        controller=MagicMock(),
        instruments={"pipette": _instrument(name="pipette", offset_x=100.0)},
    )
    protocol = _protocol(_home_step(0))

    violations = validate_protocol_semantics(protocol, instrumented_gantry, _deck(), gantry)

    assert any("home pose" in v.message for v in violations), violations
    assert any("Cub XL right X-max rail" in v.message for v in violations), violations


def test_deck_target_move_validates_safe_z_pose():
    protocol = _protocol(_move_step(0, position="plate.A1"))

    violations = validate_protocol_semantics(
        protocol,
        _board(),
        _deck(),
        _gantry(safe_z=50.0),
    )

    assert any("safe_z" in v.message for v in violations), violations


def test_scan_action_z_inside_machine_structure_fails():
    protocol = Protocol([
        ProtocolStep(
            index=0,
            command_name="scan",
            handler=lambda *a, **k: None,
            args={
                "plate": "plate",
                "instrument": "asmi",
                "method": "indentation",
                "measurement_height": 10.0,
                "interwell_scan_height": 80.0,
                "indentation_limit_height": -20.0,
                "method_kwargs": {"step_size": 0.1},
            },
        )
    ])

    violations = validate_protocol_semantics(
        protocol, _board(), _deck(), _gantry(),
    )

    assert any("action_z" in v.message for v in violations), violations


def _eight_channel_board(axis="x", height=120):
    from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
    return InstrumentedGantry(controller=MagicMock(), instruments={
        "pipette": OpentronsPipette(
            pipette_model="p300_multi_gen2", offline=True,
            channel_geometry=dict(axis=axis, length_mm=80, width_mm=30, height_mm=height),
        ),
    })


def test_eight_channel_far_end_hits_rail_while_reference_tip_is_clear():
    protocol = _protocol(_move_step(0, position=(410, 150, 40), instrument="pipette"))
    assert any("right X-max rail" in v.message for v in validate_protocol_semantics(
        protocol, _eight_channel_board("x"), _deck(), _gantry(),
    ))
    assert validate_protocol_semantics(protocol, _eight_channel_board("y"), _deck(), _gantry()) == []


def test_eight_channel_transverse_width_hits_rail():
    protocol = _protocol(_move_step(0, position=(470, 150, 40), instrument="pipette"))
    assert any("right X-max rail" in v.message for v in validate_protocol_semantics(
        protocol, _eight_channel_board("y"), _deck(), _gantry(),
    ))


def test_eight_channel_sweep_hits_between_clear_endpoints():
    protocol = _protocol(
        _move_step(0, position=(400, 150, 90), instrument="pipette"),
        _move_step(1, position=(560, 150, 90), instrument="pipette", travel_z=40),
    )
    violations = validate_protocol_semantics(protocol, _eight_channel_board(), _deck(), _gantry())
    assert any("travel segment" in v.message and "right X-max rail" in v.message for v in violations)
    high = _protocol(
        _move_step(0, position=(400, 150, 90), instrument="pipette"),
        _move_step(1, position=(560, 150, 90), instrument="pipette", travel_z=90),
    )
    assert validate_protocol_semantics(high, _eight_channel_board(), _deck(), _gantry()) == []


def test_eight_channel_swept_geometry_translates_with_home_origin():
    from dataclasses import replace
    from cubos.gantry.gantry_config import OriginPolicy
    gantry = replace(_gantry(), origin_policy=OriginPolicy.HOME_ORIGIN,
        working_volume=WorkingVolume(-540, 0, -300, 0, -160, 0))
    protocol = _protocol(_move_step(0, position=(-130, -150, -60), instrument="pipette"))
    assert any("right X-max rail" in v.message for v in validate_protocol_semantics(
        protocol, _eight_channel_board(), _deck(), gantry,
    ))


def test_eight_channel_home_checks_full_head():
    from dataclasses import replace
    gantry = replace(_gantry(x_max=410), working_volume=WorkingVolume(0, 410, 0, 200, 0, 70))
    assert any("home pose" in v.message and "right X-max rail" in v.message
        for v in validate_protocol_semantics(_protocol(_home_step(0)), _eight_channel_board(), _deck(), gantry))


def test_eight_channel_body_height_includes_attached_tip_extension():
    from pathlib import Path
    from cubos.deck.loader import load_deck_from_yaml
    deck = load_deck_from_yaml(Path(__file__).parents[1] / "fixtures/configs/pipette_tip_transfer/deck.yaml")
    board = _eight_channel_board(height=20)
    protocol = _protocol(
        ProtocolStep(index=0, command_name="pick_up_tip", handler=lambda **kw: None, args={"position": "tip_rack.A1"}),
        _move_step(1, position=(410, 150, -50), instrument="pipette", travel_z=90),
    )
    violations = validate_protocol_semantics(protocol, board, deck, _gantry(safe_z=90))
    assert any(v.step_index == 1 and "instrument envelope" in v.message and "right X-max rail" in v.message for v in violations)
