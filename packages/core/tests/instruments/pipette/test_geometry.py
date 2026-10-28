from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from cubos.gantry.instrument_loader import build_instrumented_gantry
from cubos.instruments.pipette.geometry import EightChannelGeometry, resolve_channel_geometry
from cubos.instruments.pipette.models import PIPETTE_MODELS, PICUS2_MODELS
from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette
from cubos.instruments.yaml_schema import InstrumentYamlEntry

GEOMETRY = dict(axis="x", spacing_mm=9.0, length_mm=80.0, width_mm=30.0, height_mm=120.0)


@pytest.mark.parametrize("axis,reference,bounds", [
    ("x", "leftmost", (-8.5, 71.5, -15, 15)),
    ("y", "frontmost", (-15, 15, -8.5, 71.5)),
])
def test_geometry_is_anchored_at_end_nozzle(axis, reference, bounds):
    geometry = EightChannelGeometry(**{**GEOMETRY, "axis": axis})
    assert geometry.reference_tip == reference
    assert geometry.xy_bounds == bounds


@pytest.mark.parametrize("field,value", [
    ("axis", "z"), ("axis", "-x"), ("spacing_mm", 0),
    ("spacing_mm", float("inf")), ("spacing_mm", True),
    ("length_mm", 63), ("length_mm", -80), ("width_mm", 0),
    ("height_mm", float("nan")), ("height_mm", "120"), ("typo", 80),
])
def test_invalid_geometry_rejected(field, value):
    with pytest.raises(ValidationError):
        EightChannelGeometry(**{**GEOMETRY, field: value})


@pytest.mark.parametrize("driver,models,vendor", [
    (OpentronsPipette, PIPETTE_MODELS, "opentrons"),
    (SartoriusPicus2Pipette, PICUS2_MODELS, "sartorius"),
])
def test_all_eight_channel_models_require_measured_geometry(driver, models, vendor):
    for name, model in models.items():
        if model.channels != 8:
            continue
        with pytest.raises(ValueError, match="require channel_geometry"):
            driver(pipette_model=name, offline=True)
        entry = dict(type="pipette", vendor=vendor, pipette_model=name)
        with pytest.raises(ValidationError, match="require channel_geometry"):
            InstrumentYamlEntry(**entry)
        parsed = InstrumentYamlEntry(**entry, channel_geometry=GEOMETRY)
        board = build_instrumented_gantry({"pipette": parsed.model_dump()}, MagicMock(), mock_mode=True)
        assert board.instruments["pipette"].channel_geometry.xy_bounds == (-8.5, 71.5, -15, 15)


def test_single_channel_and_96_channel_do_not_acquire_eight_channel_geometry():
    for channels in (1, 96):
        assert resolve_channel_geometry(channels, None) is None
        with pytest.raises(ValueError, match="only supported for 8-channel"):
            resolve_channel_geometry(channels, GEOMETRY)
    assert OpentronsPipette(offline=True).channel_geometry is None


@pytest.mark.parametrize("axis", ["x", "y"])
def test_move_uses_reference_tip_without_half_span_shift(axis):
    controller = MagicMock()
    controller.current_position.return_value = (0, 0, 0)
    board = build_instrumented_gantry({"pipette": dict(
        type="pipette", vendor="opentrons", pipette_model="p300_multi_gen2",
        offset_x=10, offset_y=-5, depth=20,
        channel_geometry={**GEOMETRY, "axis": axis},
    )}, controller, mock_mode=True, safe_z=100)
    board.instruments["pipette"].set_attached_tip_extension(50)
    board.move("pipette", (100, 150, 10), travel_z=90)
    controller.move_to.assert_called_once_with(90, 155, 80, travel_z=160)


def test_geometry_requires_explicit_model():
    with pytest.raises(ValidationError, match="explicit 8-channel pipette_model"):
        InstrumentYamlEntry(type="pipette", vendor="opentrons", channel_geometry=GEOMETRY)


@pytest.mark.parametrize("model", [[], {}, 8, True])
def test_non_string_model_is_a_validation_error(model):
    with pytest.raises(ValidationError, match="pipette_model must be a string"):
        InstrumentYamlEntry(type="pipette", vendor="opentrons", pipette_model=model)
