"""Unsupported frames fail before controller access or coordinate rewriting."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cubos.gantry.gantry import Gantry
from cubos.gantry.gantry_config import GantryConfig, GantryType, WorkingVolume
from cubos.gantry.machine_geometry import fixed_structures_for_gantry
from cubos.gantry.offset_calibration import calibrate_instrument_offsets
from cubos.gantry.origin import (
    build_deck_origin_calibration_plan,
    calibrated_origin_frame,
    translate_calibrated_safe_z,
    validate_deck_origin_minima,
    validate_working_volume_origin,
)
from cubos.gantry.session import GantrySession
from cubos.tools.calibration.single_instrument_calibration import _updated_gantry_yaml_text
from cubos.tools.calibration.multi_instrument_calibration import _updated_yaml_text


VOLUME = dict(x_min=0, x_max=300, y_min=0, y_max=200, z_min=0, z_max=80)
PARAMS = dict(home_z=80, block_touch_z=35, block_height=35)


@pytest.mark.parametrize("policy", ["home_origin", "unknown", None])
def test_config_and_runtime_reject_explicit_unsupported_policy_before_initializing_controller(monkeypatch, policy):
    mill = Mock()
    monkeypatch.setattr("cubos.gantry.gantry.Mill", mill)
    with pytest.raises(ValueError):
        Gantry({"origin_policy": policy})
    mill.assert_not_called()
    with pytest.raises(ValueError, match="origin_policy"):
        GantryConfig(serial_port="/dev/test", gantry_type=GantryType.CUB_XL,
                     factory_z_travel_mm=80, working_volume=WorkingVolume(**VOLUME), origin_policy=policy)


@pytest.mark.parametrize("policy", ["home_origin", "unknown"])
def test_public_origin_math_rejects_unsupported_frames(policy):
    with pytest.raises(ValueError):
        calibrated_origin_frame(policy, {"x": 300, "y": 200}, z_min=0, z_max=80)
    for previous, selected in ((policy, "deck_origin"), ("deck_origin", policy)):
        with pytest.raises(ValueError):
            translate_calibrated_safe_z(70, previous, selected, 80, VOLUME)
    config = SimpleNamespace(origin_policy=policy, working_volume=WorkingVolume(**VOLUME), gantry_type=GantryType.CUB_XL)
    for helper in (validate_deck_origin_minima, validate_working_volume_origin,
                   build_deck_origin_calibration_plan, fixed_structures_for_gantry):
        with pytest.raises(ValueError):
            helper(config)
    with pytest.raises(ValueError):
        calibrate_instrument_offsets({"origin_policy": policy}, "pipette", {})


@pytest.mark.parametrize("policy", ["home_origin", "unknown"])
def test_session_direct_refresh_and_finalization_reject_before_actuation(policy):
    session = GantrySession()
    controller = Mock()
    session._gantry = controller
    session._connected_gantry_config = {"origin_policy": "deck_origin"}
    with pytest.raises(ValueError):
        session.refresh_connected_config("gantry.yaml", {"origin_policy": policy})
    with pytest.raises(ValueError):
        session.finalize_calibration_origin(**PARAMS, factory_z_travel=80, origin_policy=policy)
    assert not controller.mock_calls


@pytest.mark.parametrize("configured,requested", [("deck_origin", "home_origin"), ("home_origin", "deck_origin")])
def test_direct_gantry_finalizer_never_reinterprets_an_existing_frame(configured, requested):
    gantry = Gantry(offline=True)
    gantry.config["origin_policy"] = configured
    gantry._offline = False
    gantry._mill = Mock()
    with pytest.raises(ValueError):
        gantry.finalize_deck_origin_calibration(**PARAMS, total_z_range=80, origin_policy=requested)
    assert not gantry._mill.mock_calls


@pytest.mark.parametrize("writer", ["single", "multi"])
@pytest.mark.parametrize("configured,requested", [("home_origin", "deck_origin"), ("deck_origin", "home_origin"), ("deck_origin", "unknown")])
def test_cli_writers_reject_legacy_or_unknown_frames_without_rewriting_config(writer, configured, requested):
    raw = {"origin_policy": configured, "working_volume": deepcopy(VOLUME)}
    original = deepcopy(raw)
    kwargs = dict(measured_coords={"x": 300, "y": 200, "z": 80}, z_min_mm=0, z_max_mm=80, origin_policy=requested)
    with pytest.raises(ValueError):
        if writer == "single":
            _updated_gantry_yaml_text(raw, **kwargs)
        else:
            _updated_yaml_text(raw, **kwargs, instrument_calibrations={}, max_travel={"x": 301, "y": 201, "z": 81}, calibration_block_height_mm=35)
    assert raw == original


@pytest.mark.parametrize("config", [{}, {"origin_policy": "deck_origin"}])
def test_implicit_and_explicit_deck_origin_remain_compatible(config):
    gantry = Gantry(config, offline=True)
    assert gantry.get_position_info()["status"] == "Idle"
    bounds, home = calibrated_origin_frame(config.get("origin_policy", "deck_origin"), {"x": 300, "y": 200}, z_min=10, z_max=90)
    assert bounds["z_min"] == 10
    assert home == {"x": 300, "y": 200, "z": 90}


@pytest.mark.parametrize("policy", [None, "deck_origin"])
def test_unlabeled_or_mislabeled_legacy_bounds_fail_before_controller_access(monkeypatch, policy):
    from cubos.gantry.yaml_schema import GantryYamlSchema

    raw = {"serial_port": "/dev/test", "gantry_type": "cub_xl",
           "cnc": {"factory_z_travel_mm": 80},
           "working_volume": dict(x_min=-300, x_max=0, y_min=-200, y_max=0, z_min=-80, z_max=0)}
    if policy is not None:
        raw["origin_policy"] = policy
    mill = Mock()
    monkeypatch.setattr("cubos.gantry.gantry.Mill", mill)
    with pytest.raises(ValueError, match="Legacy home-frame"):
        Gantry(raw)
    mill.assert_not_called()
    with pytest.raises(ValueError, match="Legacy home-frame"):
        GantryYamlSchema.model_validate(raw)
    with pytest.raises(ValueError, match="Legacy home-frame"):
        GantryConfig(serial_port="/dev/test", gantry_type=GantryType.CUB_XL,
                     factory_z_travel_mm=80, working_volume=WorkingVolume(**raw["working_volume"]))
    with pytest.raises(ValueError, match="Legacy home-frame"):
        GantrySession().refresh_connected_config("gantry.yaml", raw)
    with pytest.raises(ValueError, match="Legacy home-frame"):
        calibrate_instrument_offsets(raw, "pipette", {})
    controller = Mock()
    session = GantrySession()
    session._gantry = controller
    session._connected_gantry_config = raw
    with pytest.raises(ValueError, match="Legacy home-frame"):
        session.finalize_calibration_origin(**PARAMS, factory_z_travel=80)
    assert not controller.mock_calls
    writer_args = dict(measured_coords={"x": 300, "y": 200, "z": 80}, z_min_mm=0, z_max_mm=80)
    with pytest.raises(ValueError, match="Legacy home-frame"):
        _updated_gantry_yaml_text(raw, **writer_args)
    with pytest.raises(ValueError, match="Legacy home-frame"):
        _updated_yaml_text(raw, **writer_args, instrument_calibrations={}, max_travel={"x": 301, "y": 201, "z": 81}, calibration_block_height_mm=35)


def test_deck_xy_overtravel_keeps_its_frame_and_bounds():
    from cubos.gantry.yaml_schema import GantryYamlSchema

    raw = {"serial_port": "/dev/test", "gantry_type": "cub_xl",
           "cnc": {"factory_z_travel_mm": 80},
           "working_volume": VOLUME | {"x_min": -20, "y_min": -5}}
    schema = GantryYamlSchema.model_validate(raw)
    assert schema.origin_policy == "deck_origin"
    assert schema.working_volume.x_min == -20
    assert Gantry(raw, offline=True).config["working_volume"] == raw["working_volume"]


def test_connect_revalidates_mutated_config_before_any_transport_access():
    gantry = Gantry(offline=True)
    gantry._offline = False
    gantry._mill = Mock()
    gantry.config["origin_policy"] = "home_origin"
    with pytest.raises(ValueError):
        gantry.connect()
    assert not gantry._mill.mock_calls
