"""Tests for the ``measure`` protocol command."""

import logging
from unittest.mock import MagicMock

import pytest

from data.data_store import DataStore
from deck.deck import Deck
from deck.labware.labware import Coordinate3D
from deck.labware.well_plate import WellPlate
from instruments.base_instrument import BaseInstrument
from instruments.filmetrics.models import MeasurementResult
from instruments.uv_curing.models import CureResult
from protocol_engine.commands.measure import measure
from protocol_engine.errors import ProtocolExecutionError
from protocol_engine.runtime import ProtocolContext


HEIGHT_MM = 14.10


def _mock_instr():
    instr = MagicMock(spec=BaseInstrument)
    instr.name = "uvvis"
    instr.offset_x = 0.0
    instr.offset_y = 0.0
    instr.depth = 0.0
    instr.measure = MagicMock(return_value="spectrum")
    return instr


def _ctx(instr, well_coord=None, height=HEIGHT_MM):
    well_coord = well_coord or Coordinate3D(x=10.0, y=20.0, z=height or 0.0)
    board = MagicMock()
    board.instruments = {"uvvis": instr}
    deck = MagicMock()
    deck.resolve_coordinate = MagicMock(return_value=well_coord)
    labware = MagicMock(height=height)
    deck.__getitem__ = MagicMock(return_value=labware)
    return ProtocolContext(gantry=board, deck=deck)


def _plate() -> WellPlate:
    return WellPlate(
        name="test_plate",
        model_name="test_2x1",
        rows=1,
        columns=1,
        wells={"A1": Coordinate3D(x=10.0, y=20.0, z=HEIGHT_MM)},
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


class _FakeASMI:
    def indentation(
        self,
        *,
        gantry,
        well_z,
        measurement_height,
        indentation_limit_height,
        step_size=0.1,
        force_limit=10.0,
    ):
        del gantry, well_z, measurement_height, indentation_limit_height
        return {
            "measurements": [
                {
                    "timestamp": 1.0,
                    "z_mm": 13.0,
                    "raw_force_n": 0.2,
                    "corrected_force_n": 0.1,
                    "direction": "down",
                }
            ],
            "baseline_avg": 0.1,
            "baseline_std": 0.01,
            "force_exceeded": False,
            "data_points": 1,
            "measure_with_return": False,
            "step_size_mm": step_size,
            "z_target_mm": 13.0,
            "force_limit_n": force_limit,
        }


class _FakeFilmetrics:
    def measure(self):
        return MeasurementResult(thickness_nm=151.2, goodness_of_fit=0.96)


class _FakeUVCuring:
    def cure(self):
        return CureResult(
            intensity_percent=60.0,
            exposure_time_s=1.5,
            timestamp=123.4,
        )

    def health_check(self):
        return True


def test_measure_travels_at_safe_z_then_descends():
    """measure: move_to_labware (XY at safe_z), then descend to
    height + measurement_height, then call the method."""
    instr = _mock_instr()
    coord = Coordinate3D(x=10.0, y=20.0, z=HEIGHT_MM)
    ctx = _ctx(instr, well_coord=coord)

    result = measure(
        ctx, instrument="uvvis", position="plate_1.A1",
        measurement_height=2.0,
    )

    ctx.gantry.move_to_labware.assert_called_once_with("uvvis", coord)
    ctx.gantry.move.assert_called_once_with("uvvis", (10.0, 20.0, HEIGHT_MM + 2.0))
    instr.measure.assert_called_once()
    assert result == "spectrum"


def test_measure_with_negative_offset_descends_below_surface():
    """Negative measurement_height = below the labware surface."""
    instr = _mock_instr()
    coord = Coordinate3D(x=10.0, y=20.0, z=HEIGHT_MM)
    ctx = _ctx(instr, well_coord=coord)

    measure(
        ctx, instrument="uvvis", position="plate_1.A1",
        measurement_height=-1.0,
    )

    ctx.gantry.move.assert_called_once_with("uvvis", (10.0, 20.0, HEIGHT_MM - 1.0))


def test_measure_passes_method_kwargs():
    instr = _mock_instr()
    ctx = _ctx(instr)
    measure(
        ctx, instrument="uvvis", position="plate_1.A1",
        measurement_height=0.0,
        method="measure", method_kwargs={"intensity": 50},
    )
    instr.measure.assert_called_once_with(intensity=50)


def test_measure_persists_single_asmi_indentation_when_campaign_is_present():
    plate = _plate()
    board = MagicMock()
    board.controller = object()
    board.instruments = {"asmi": _FakeASMI()}
    deck = Deck({"plate_1": plate})
    store = DataStore(db_path=":memory:")
    campaign_id = store.create_campaign(description="measure")
    store.register_labware(campaign_id, "plate_1", plate)
    ctx = ProtocolContext(
        gantry=board,
        deck=deck,
        data_store=store,
        campaign_id=campaign_id,
    )

    measure(
        ctx,
        instrument="asmi",
        position="plate_1.A1",
        measurement_height=0.0,
        method="indentation",
        indentation_limit_height=-1.0,
    )

    row = store._conn.execute(
        """
        SELECT e.labware_name, e.well_id, m.sample_timestamps, m.directions,
               m.step_size_mm, m.z_target_mm, m.force_limit_n
        FROM experiments e
        JOIN asmi_measurements m ON m.experiment_id = e.id
        WHERE e.campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    assert row[0] == "test_plate"
    assert row[1] == "A1"
    assert row[2] == "[1.0]"
    assert row[3] == '["down"]'
    assert row[4] == pytest.approx(0.1)
    assert row[5] == pytest.approx(13.0)
    assert row[6] == pytest.approx(10.0)
    store.close()


def test_measure_persists_single_filmetrics_thickness_when_campaign_is_present():
    plate = _plate()
    board = MagicMock()
    board.controller = object()
    board.instruments = {"filmetrics": _FakeFilmetrics()}
    deck = Deck({"plate_1": plate})
    store = DataStore(db_path=":memory:")
    campaign_id = store.create_campaign(description="measure")
    store.register_labware(campaign_id, "plate_1", plate)
    ctx = ProtocolContext(
        gantry=board,
        deck=deck,
        data_store=store,
        campaign_id=campaign_id,
    )

    measure(
        ctx,
        instrument="filmetrics",
        position="plate_1.A1",
        measurement_height=0.0,
    )

    row = store._conn.execute(
        """
        SELECT e.labware_name, e.well_id, m.thickness_nm, m.goodness_of_fit
        FROM experiments e
        JOIN filmetrics_measurements m ON m.experiment_id = e.id
        WHERE e.campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    assert row[0] == "test_plate"
    assert row[1] == "A1"
    assert row[2] == pytest.approx(151.2)
    assert row[3] == pytest.approx(0.96)
    store.close()


def test_measure_persists_single_uv_curing_exposure_when_campaign_is_present():
    plate = _plate()
    board = MagicMock()
    board.controller = object()
    board.instruments = {"uv_curing": _FakeUVCuring()}
    deck = Deck({"plate_1": plate})
    store = DataStore(db_path=":memory:")
    campaign_id = store.create_campaign(description="measure")
    store.register_labware(campaign_id, "plate_1", plate)
    ctx = ProtocolContext(
        gantry=board,
        deck=deck,
        data_store=store,
        campaign_id=campaign_id,
    )

    measure(
        ctx,
        instrument="uv_curing",
        position="plate_1.A1",
        measurement_height=0.0,
        method="cure",
    )

    row = store._conn.execute(
        """
        SELECT e.labware_name, e.well_id, m.intensity_percent,
               m.exposure_time_s, m.cure_timestamp_s
        FROM experiments e
        JOIN uv_curing_measurements m ON m.experiment_id = e.id
        WHERE e.campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    assert row[0] == "test_plate"
    assert row[1] == "A1"
    assert row[2] == pytest.approx(60.0)
    assert row[3] == pytest.approx(1.5)
    assert row[4] == pytest.approx(123.4)
    store.close()


def test_measure_uv_health_check_does_not_persist_or_fail(caplog):
    plate = _plate()
    board = MagicMock()
    board.controller = object()
    board.instruments = {"uv_curing": _FakeUVCuring()}
    deck = Deck({"plate_1": plate})
    store = DataStore(db_path=":memory:")
    campaign_id = store.create_campaign(description="measure")
    store.register_labware(campaign_id, "plate_1", plate)
    ctx = ProtocolContext(
        gantry=board,
        deck=deck,
        data_store=store,
        campaign_id=campaign_id,
    )

    with caplog.at_level(logging.WARNING):
        result = measure(
            ctx,
            instrument="uv_curing",
            position="plate_1.A1",
            measurement_height=0.0,
            method="health_check",
        )

    assert result is True
    assert "not persistable" in caplog.text
    assert store._conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT COUNT(*) FROM uv_curing_measurements"
    ).fetchone()[0] == 0
    store.close()


def test_measure_unknown_instrument_raises():
    instr = _mock_instr()
    ctx = _ctx(instr)
    with pytest.raises(ProtocolExecutionError, match="Unknown instrument"):
        measure(
            ctx, instrument="not_a_thing", position="plate_1.A1",
            measurement_height=0.0,
        )


def test_measure_unknown_method_raises():
    instr = MagicMock(spec=BaseInstrument)
    instr.name = "uvvis"
    instr.offset_x = instr.offset_y = instr.depth = 0.0
    ctx = _ctx(instr)
    with pytest.raises(ProtocolExecutionError, match="has no method"):
        measure(
            ctx, instrument="uvvis", position="plate_1.A1",
            measurement_height=0.0, method="nope",
        )


@pytest.mark.parametrize("bad", ["", "1.0", float("nan"), True])
def test_measure_rejects_non_finite_measurement_height(bad):
    instr = _mock_instr()
    ctx = _ctx(instr)
    with pytest.raises(ProtocolExecutionError, match="finite number"):
        measure(
            ctx, instrument="uvvis", position="plate_1.A1",
            measurement_height=bad,
        )


def test_measure_rejects_legacy_indentation_limit_in_method_kwargs():
    """Measure routes its ``method_kwargs`` through the same
    legacy-rename hint table scan uses, so a user porting an old config
    that nested ``indentation_limit`` inside ``method_kwargs`` gets the
    rename hint instead of a generic Python TypeError or silent
    overwrite."""
    instr = _mock_instr()
    ctx = _ctx(instr)
    with pytest.raises(ProtocolExecutionError, match="indentation_limit_height"):
        measure(
            ctx, instrument="uvvis", position="plate_1.A1",
            measurement_height=0.0,
            method_kwargs={"indentation_limit": 5.0},
        )


def test_measure_rejects_safe_approach_height_in_method_kwargs():
    instr = _mock_instr()
    ctx = _ctx(instr)
    with pytest.raises(ProtocolExecutionError, match="interwell_scan_height"):
        measure(
            ctx, instrument="uvvis", position="plate_1.A1",
            measurement_height=0.0,
            method_kwargs={"safe_approach_height": 10.0},
        )


def test_measure_rejects_measurement_height_in_method_kwargs():
    """``measurement_height`` is a top-level command field; nesting it in
    ``method_kwargs`` would let the engine silently overwrite the user's
    value during dispatch injection."""
    instr = _mock_instr()
    ctx = _ctx(instr)
    with pytest.raises(ProtocolExecutionError, match="measurement_height"):
        measure(
            ctx, instrument="uvvis", position="plate_1.A1",
            measurement_height=0.0,
            method_kwargs={"measurement_height": 5.0},
        )
