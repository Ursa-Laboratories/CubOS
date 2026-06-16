"""Movement-plan checks using mock deck-origin YAML fixtures."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deck.loader import load_deck_from_yaml
from gantry.instrument_loader import load_instrumented_gantry_from_config
from gantry.loader import load_gantry_from_yaml
from protocol_engine.commands.scan import scan
from protocol_engine.loader import load_protocol_from_yaml
from protocol_engine.runtime import ProtocolContext
from protocol_engine.setup import setup_protocol
from validation.protocol_semantics import validate_protocol_semantics


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/configs"


def test_mock_asmi_config_generates_deck_origin_scan_waypoints():
    gantry_config = load_gantry_from_yaml(
        FIXTURES / "gantry/mock_asmi.yaml"
    )
    deck = load_deck_from_yaml(
        FIXTURES / "deck/mock_asmi_deck.yaml",
        factory_z_travel_mm=gantry_config.factory_z_travel_mm,
    )
    mock_gantry = MagicMock()
    mock_gantry.get_coordinates.return_value = {"x": 0.0, "y": 0.0, "z": 85.0}
    instrumented_gantry = load_instrumented_gantry_from_config(
        gantry_config, mock_gantry, mock_mode=True,
    )
    indentation_calls = []

    def fake_indentation(
        *,
        measurement_height=None,
        indentation_limit_height=None,
        well_z=None,
        gantry=None,
        **kwargs,
    ):
        indentation_calls.append({
            "measurement_height": measurement_height,
            "indentation_limit_height": indentation_limit_height,
            "well_z": well_z,
            "gantry": gantry,
            **kwargs,
        })
        return {"ok": True}

    instrumented_gantry.instruments["asmi"].indentation = fake_indentation
    protocol = load_protocol_from_yaml(
        FIXTURES / "protocol/mock_asmi_indentation.yaml"
    )

    scan_step = next(step for step in protocol.steps if step.command_name == "scan")
    assert validate_protocol_semantics(
        protocol, instrumented_gantry, deck, gantry_config,
    ) == []

    ctx = ProtocolContext(
        gantry=instrumented_gantry,
        deck=deck,
        positions=protocol.positions,
        gantry_config=gantry_config,
        logger=logging.getLogger("test_asmi_config"),
    )
    scan(ctx, **scan_step.args)

    moves = mock_gantry.move_to.call_args_list
    first_well = deck["plate"].get_well_center("A1")
    second_well = deck["plate"].get_well_center("A2")
    last_well = deck["plate"].get_well_center("H12")
    plate_obj = deck["plate"]
    instr = instrumented_gantry.instruments["asmi"]
    safe_z = gantry_config.resolved_safe_z
    interwell_scan_height = scan_step.args["interwell_scan_height"]
    measurement_height = scan_step.args["measurement_height"]
    indentation_limit_height = scan_step.args["indentation_limit_height"]
    # Heights are labware-relative; the well's calibrated Z is the
    # surface reference, not the plate's outer ``height`` (a dimension).
    surface_z = plate_obj.get_well_center("A1").z
    approach_abs = surface_z + interwell_scan_height
    action_abs = surface_z + measurement_height

    # First well: move_to_labware travels XY at safe_z, then descends to
    # approach plane, then to action plane.
    assert moves[0].args == pytest.approx(
        (first_well.x, first_well.y, safe_z)
    )
    assert moves[0].kwargs == {"travel_z": safe_z}
    assert moves[1].args == pytest.approx(
        (first_well.x, first_well.y, approach_abs)
    )
    assert moves[2].args == pytest.approx(
        (first_well.x, first_well.y, action_abs)
    )
    # Subsequent well: travels at approach plane.
    assert moves[3].args == pytest.approx(
        (second_well.x, second_well.y, approach_abs)
    )
    assert moves[3].kwargs == {"travel_z": approach_abs}
    # Final retract.
    assert moves[-1].args == pytest.approx(
        (last_well.x, last_well.y, approach_abs)
    )
    assert moves[-1].kwargs == {"travel_z": approach_abs}

    assert indentation_calls[0]["measurement_height"] == measurement_height
    assert indentation_calls[0]["indentation_limit_height"] == indentation_limit_height
    assert indentation_calls[0]["well_z"] == surface_z
    assert indentation_calls[0]["gantry"] is mock_gantry


def test_mock_panda_deck_origin_layout_and_placeholders_parse():
    gantry_config = load_gantry_from_yaml(
        FIXTURES / "gantry/mock_panda.yaml"
    )
    deck = load_deck_from_yaml(
        FIXTURES / "deck/mock_panda_deck.yaml",
        factory_z_travel_mm=gantry_config.factory_z_travel_mm,
    )
    plate = deck.resolve_coordinate("well_plate_holder.plate.A1")
    plate_a2 = deck.resolve_coordinate("well_plate_holder.plate.A2")
    tip_a1 = deck.resolve_coordinate("tip_rack_left.A1")
    tip_a2 = deck.resolve_coordinate("tip_rack_left.A2")

    assert plate_a2.x == pytest.approx(plate.x)
    assert plate_a2.y > plate.y
    assert tip_a2.x == pytest.approx(tip_a1.x)
    assert tip_a2.y > tip_a1.y
    assert deck.resolve_coordinate("vial_holder.vial_9").z > deck["vial_holder"].location.z
    assert set(gantry_config.instruments) == {
        "potentiostat",
        "camera",
        "vial_capper_decapper",
    }


def test_mock_filmetrics_deck_origin_config_validates_setup():
    gantry_path = FIXTURES / "gantry/mock_filmetrics.yaml"
    deck_path = FIXTURES / "deck/mock_filmetrics_deck.yaml"
    protocol_path = FIXTURES / "protocol/mock_filmetrics_scan.yaml"

    gantry_config = load_gantry_from_yaml(gantry_path)
    deck = load_deck_from_yaml(deck_path, factory_z_travel_mm=gantry_config.factory_z_travel_mm)
    instrumented_gantry = load_instrumented_gantry_from_config(
        gantry_config, MagicMock(), mock_mode=True,
    )
    protocol = load_protocol_from_yaml(protocol_path)

    plate = deck["plate_1"]
    a1 = plate.get_well_center("A1")
    a2 = plate.get_well_center("A2")

    assert (a1.x, a1.y, a1.z) == pytest.approx((270.0, 140.0, 70.0))
    assert (a2.x, a2.y, a2.z) == pytest.approx((270.0, 131.0, 70.0))
    scan_step = next(step for step in protocol.steps if step.command_name == "scan")
    assert scan_step.args["measurement_height"] == pytest.approx(10.0)
    # The well's deck-frame Z (the calibration anchor's z) is the surface
    # reference. The plate's ``height`` is the physical outer dimension
    # (from the SBS96 definition).
    assert a1.z == pytest.approx(70.0)
    assert plate.height == pytest.approx(14.35)
    assert validate_protocol_semantics(
        protocol, instrumented_gantry, deck, gantry_config,
    ) == []

    setup_protocol(
        gantry_path,
        deck_path,
        protocol_path,
        mock_mode=True,
    )


def test_sharc_motion_scan_config_does_not_call_uv_cure():
    protocol, context = setup_protocol(
        FIXTURES / "gantry/mock_sharc.yaml",
        FIXTURES / "deck/mock_nested_plate_deck.yaml",
        FIXTURES / "protocol/mock_sharc_uv_motion_scan.yaml",
    )
    uv = context.gantry.instruments["uv_curing"]
    uv.cure = MagicMock(side_effect=AssertionError("cure should not be called"))
    uv.health_check = MagicMock(return_value=True)

    result = protocol.execute(context)

    assert len(result[0]) == 96
    assert uv.health_check.call_count == 96
    uv.cure.assert_not_called()


def test_cubxl_multi_instrument_candidate_validates_with_park_protocol():
    _, context = setup_protocol(
        FIXTURES / "gantry/mock_cubxl_multi_instrument.yaml",
        FIXTURES / "deck/mock_cubxl_multi_instrument_deck.yaml",
        FIXTURES / "protocol/mock_cubxl_multi_instrument_park.yaml",
    )
    assert context.gantry.instruments["potentiostat"]._offline is True


def test_cubxl_multi_instrument_vial_scan_visits_vials_in_alternating_order():
    protocol, context = setup_protocol(
        FIXTURES / "gantry/mock_cubxl_multi_instrument.yaml",
        FIXTURES / "deck/mock_cubxl_multi_instrument_deck.yaml",
        FIXTURES / "protocol/mock_cubxl_multi_instrument_vial_scan.yaml",
    )

    move_positions = [
        step.args["position"]
        for step in protocol.steps
        if step.command_name == "move"
    ]

    assert move_positions == [
        "park_position",
        "vial_1_scan",
        "vial_8_scan",
        "vial_2_scan",
        "vial_7_scan",
        "vial_3_scan",
        "vial_6_scan",
        "vial_4_scan",
        "vial_5_scan",
        "park_position",
    ]
    assert context.gantry.instruments["potentiostat"]._offline is True
