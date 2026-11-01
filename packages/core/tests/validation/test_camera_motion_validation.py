"""Camera paths must pass the same bounds and obstacle checks as other motion."""

from types import SimpleNamespace

import pytest

from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.well_plate import WellPlate
from cubos.gantry.gantry_config import GantryConfig, GantryType, WorkingVolume
from cubos.gantry.instrument_mount import InstrumentedGantry
from cubos.gantry.machine_geometry import FixedStructureBox
from cubos.instruments.camera.vendors.flir import FlirCamera
from cubos.protocol_engine.commands.camera import image_well
from cubos.protocol_engine.protocol import Protocol, ProtocolStep
from cubos.protocol_engine.runtime import ProtocolContext
from cubos.validation.bounds import collect_protocol_motion_targets, validate_protocol_motion_bounds
from cubos.validation.protocol_semantics import validate_protocol_semantics


def rig(*, x=470.0, depth=0.0, safe_z=90.0, **args):
    config = GantryConfig(
        serial_port="/dev/null", gantry_type=GantryType.CUB_XL,
        factory_z_travel_mm=100.0, safe_z=safe_z,
        working_volume=WorkingVolume(x_min=0, x_max=540, y_min=0, y_max=300, z_min=0, z_max=100),
    )
    camera = FlirCamera(name="camera", offline=True, depth=depth)
    gantry = InstrumentedGantry(
        SimpleNamespace(config={"working_volume": {"z_max": 100.0}}),
        {"camera": camera}, safe_z=safe_z,
    )
    deck = Deck({"plate": WellPlate(
        name="plate", model_name="test", length=127, width=85, height=14,
        rows=1, columns=1, wells={"A1": Coordinate3D(x=x, y=50, z=0)},
        capacity_ul=200, working_volume_ul=150,
    )})
    protocol = Protocol([ProtocolStep(index=0, command_name="image_well", handler=image_well,
        args={"camera": "camera", "well": "plate.A1", "image_height": 50.0, "light": "off", **args})])
    return config, gantry, deck, protocol


def validate(r):
    config, gantry, deck, protocol = r
    return (
        validate_protocol_motion_bounds(config, protocol, deck, gantry),
        validate_protocol_semantics(protocol, gantry, deck, config),
    )


def test_sweep_into_fixed_rail_is_rejected():
    bounds, semantics = validate(rig(x_sweep_start_mm=0, x_sweep_stop_mm=40, x_sweep_step_mm=20))
    assert bounds == []
    assert any("right X-max rail" in v.message for v in semantics)


def test_segment_collision_is_rejected_even_when_capture_points_are_clear(monkeypatch):
    box = FixedStructureBox("test obstruction", 480, 490, 40, 60, 0, 80)
    monkeypatch.setattr("cubos.validation.protocol_semantics.fixed_structures_for_gantry", lambda _: (box,))
    bounds, semantics = validate(rig(x_sweep_start_mm=0, x_sweep_stop_mm=40, x_sweep_step_mm=40))
    assert bounds == []
    assert any("travel segment" in v.message for v in semantics)
    assert not any("instrument point" in v.message for v in semantics)


@pytest.mark.parametrize("args", [
    {"x_sweep_start_mm": -40, "x_sweep_stop_mm": 0, "x_sweep_step_mm": 20},
    {"x_sweep_start_mm": 0, "x_sweep_stop_mm": -40, "x_sweep_step_mm": -20},
    {"x_sweep_start_mm": 0, "x_sweep_stop_mm": 11, "x_sweep_step_mm": 20},
    {"image_height": 90, "x_sweep_start_mm": 0, "x_sweep_stop_mm": 40, "x_sweep_step_mm": 20},
])
def test_clear_sweeps_pass(args):
    assert validate(rig(**args)) == ([], [])


def test_raised_camera_uses_real_clearance_in_bounds_and_runtime(monkeypatch, tmp_path):
    r = rig(x=50, depth=-60, safe_z=20, image_height=70)
    config, gantry, deck, protocol = r
    assert validate(r) == ([], [])
    targets = collect_protocol_motion_targets(config, protocol, deck, gantry)
    assert [target.z for target in targets] == [160.0, 70.0, 160.0]
    moves = []
    gantry.controller.get_coordinates = lambda: {"x": 50, "y": 50, "z": 100.0}
    gantry.controller.move_to = lambda x, y, z, travel_z=None: moves.append((x, y, z, travel_z))
    gantry.instruments["camera"].capture = lambda save_path: save_path
    monkeypatch.setenv("CUBOS_IMAGES_DIR", str(tmp_path))
    monkeypatch.setattr("cubos.protocol_engine.commands.camera.time.sleep", lambda _: None)
    image_well(ProtocolContext(gantry=gantry, deck=deck), **protocol.steps[0].args)
    assert moves == [(50, 50, 10.0, 100.0), (50, 50, 100.0, None)]


@pytest.mark.parametrize("args", [
    {"image_height": 110, "mode": "curvature", "z_steps": 3, "z_step_mm": 20},
    {"image_height": 10, "mode": "curvature", "z_steps": 3, "z_step_mm": 20},
    {"x_offset_mm": 100}, {"y_offset_mm": -60},
])
def test_all_capture_planes_and_offsets_are_checked(args):
    bounds, semantics = validate(rig(**args))
    assert bounds
    assert any("outside working volume" in v.message for v in semantics)


@pytest.mark.parametrize("args, field", [
    ({"image_height": float("nan")}, "image_height"),
    ({"x_offset_mm": float("inf")}, "x_offset_mm"),
    ({"y_offset_mm": True}, "y_offset_mm"),
    ({"mode": "curvature", "z_steps": 1.5}, "z_steps"),
    ({"mode": "curvature", "z_step_mm": float("nan")}, "z_step_mm"),
    ({"x_sweep_start_mm": 0, "x_sweep_stop_mm": 1001}, "1000"),
])
def test_invalid_motion_is_rejected_by_semantics(args, field):
    _, semantics = validate(rig(**args))
    assert any(field in v.message for v in semantics)
