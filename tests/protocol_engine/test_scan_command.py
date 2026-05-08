"""Tests for the scan protocol command.

The scan command's per-well motion under the labware-relative model is:

* **First well of the plate**: ``move_to_labware`` (travels XY at gantry
  ``safe_z``) → raw move to ``height + interwell_scan_height`` →
  raw move to ``height + measurement_height`` → call instrument method.
* **Subsequent wells**: raw move to ``height + interwell_scan_height``
  with ``travel_z`` set so XY travel happens at that height → raw move to
  the action plane → call instrument method.
* **End of scan**: raw move that lifts back to ``height + interwell_scan_height``.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from deck.labware.labware import Coordinate3D
from deck.labware.well_plate import WellPlate
from instruments.base_instrument import BaseInstrument
from instruments.uvvis_ccs.models import UVVisSpectrum
from protocol_engine.errors import ProtocolExecutionError
from protocol_engine.measurements import InstrumentMeasurement
from protocol_engine.protocol import ProtocolContext


HEIGHT_MM = 14.10
SAFE_APPROACH = 10.0
MEASUREMENT = 1.0
APPROACH_ABS = HEIGHT_MM + SAFE_APPROACH
ACTION_ABS = HEIGHT_MM + MEASUREMENT


def _make_2x2_plate() -> WellPlate:
    return WellPlate(
        name="plate_1",
        model_name="test_96",
        length=127.71,
        width=85.43,
        height=HEIGHT_MM,
        rows=2,
        columns=2,
        wells={
            "A1": Coordinate3D(x=0.0, y=0.0, z=HEIGHT_MM),
            "A2": Coordinate3D(x=10.0, y=0.0, z=HEIGHT_MM),
            "B1": Coordinate3D(x=0.0, y=8.0, z=HEIGHT_MM),
            "B2": Coordinate3D(x=10.0, y=8.0, z=HEIGHT_MM),
        },
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


def _make_2x3_plate() -> WellPlate:
    return WellPlate(
        name="plate_2",
        model_name="test_model",
        length=127.71,
        width=85.43,
        height=HEIGHT_MM,
        rows=2,
        columns=3,
        wells={
            "A1": Coordinate3D(x=0.0, y=0.0, z=HEIGHT_MM),
            "A2": Coordinate3D(x=10.0, y=0.0, z=HEIGHT_MM),
            "A3": Coordinate3D(x=20.0, y=0.0, z=HEIGHT_MM),
            "B1": Coordinate3D(x=0.0, y=8.0, z=HEIGHT_MM),
            "B2": Coordinate3D(x=10.0, y=8.0, z=HEIGHT_MM),
            "B3": Coordinate3D(x=20.0, y=8.0, z=HEIGHT_MM),
        },
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


class _FakeSensor(BaseInstrument):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.call_count = 0
        self._return_value = True

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def measure(self) -> bool:
        self.call_count += 1
        return self._return_value

    def indentation(
        self,
        *,
        measurement_height: float,
        indentation_limit_height: float,
        well_z: float,
        gantry=None,
    ) -> dict:
        self.call_count += 1
        return {
            "measurement_height": measurement_height,
            "indentation_limit_height": indentation_limit_height,
            "well_z": well_z,
            "gantry": gantry,
        }


def _make_sensor(**kwargs) -> _FakeSensor:
    defaults = dict(name="sensor", offset_x=0.0, offset_y=0.0, depth=0.0)
    defaults.update(kwargs)
    return _FakeSensor(**defaults)


def _mock_context(
    plate: WellPlate | None = None,
    sensor: _FakeSensor | None = None,
) -> ProtocolContext:
    plate = plate or _make_2x2_plate()
    sensor = sensor or _make_sensor()

    board = MagicMock()
    board.instruments = {"uvvis": sensor}

    deck = MagicMock()
    deck.__getitem__ = MagicMock(return_value=plate)

    return ProtocolContext(
        board=board,
        deck=deck,
        logger=logging.getLogger("test_scan_command"),
    )


def _scan_args(**overrides):
    args = {
        "plate": "plate_1",
        "instrument": "uvvis",
        "method": "measure",
        "measurement_height": MEASUREMENT,
        "interwell_scan_height": SAFE_APPROACH,
    }
    args.update(overrides)
    return args


class TestScanCommand:

    def test_first_well_uses_move_to_labware(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        scan(ctx, **_scan_args())

        assert ctx.board.move_to_labware.call_count == 1

    def test_visits_wells_in_row_major_order(self):
        from protocol_engine.commands.scan import scan

        plate = _make_2x3_plate()
        ctx = _mock_context(plate=plate)

        scan(ctx, plate="plate_2", instrument="uvvis", method="measure",
             measurement_height=MEASUREMENT, interwell_scan_height=SAFE_APPROACH)

        action_zs = [
            c for c in ctx.board.move.call_args_list
            if c.args[1][2] == ACTION_ABS
        ]
        xs = [c.args[1][0] for c in action_zs]
        assert xs == [0.0, 10.0, 20.0, 0.0, 10.0, 20.0]

    def test_per_well_motion_uses_relative_offsets(self):
        """First well: move_to_labware → approach Z → action Z.
        Subsequent wells: approach (with travel_z) → action Z.
        Plus a final retract."""
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        scan(ctx, **_scan_args())

        zs = [c.args[1][2] for c in ctx.board.move.call_args_list]
        assert zs == [
            APPROACH_ABS, ACTION_ABS,    # A1
            APPROACH_ABS, ACTION_ABS,    # A2
            APPROACH_ABS, ACTION_ABS,    # B1
            APPROACH_ABS, ACTION_ABS,    # B2
            APPROACH_ABS,                # final retract
        ]

    def test_first_well_descend_does_not_pass_travel_z(self):
        """Action descents must NOT pass travel_z (would re-introduce
        the lift-then-drop detour)."""
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        scan(ctx, **_scan_args())

        action_calls = [
            c for c in ctx.board.move.call_args_list
            if c.args[1][2] == ACTION_ABS
        ]
        for call in action_calls:
            assert call.kwargs.get("travel_z") is None

    def test_subsequent_wells_use_travel_z_for_xy_at_approach(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        scan(ctx, **_scan_args())

        approach_calls = [
            c for c in ctx.board.move.call_args_list
            if c.args[1][2] == APPROACH_ABS and c.kwargs.get("travel_z") is not None
        ]
        assert len(approach_calls) == 4
        for call in approach_calls:
            assert call.kwargs["travel_z"] == APPROACH_ABS

    def test_final_retract_returns_to_safe_approach(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        scan(ctx, **_scan_args())

        last_move = ctx.board.move.call_args_list[-1]
        instr_name, position = last_move.args
        assert instr_name == "uvvis"
        assert position == (10.0, 8.0, APPROACH_ABS)
        assert last_move.kwargs.get("travel_z") == APPROACH_ABS

    def test_measurement_height_from_command_arg_drives_action_z(self):
        """Action plane is `plate.height + scan.measurement_height`."""
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        scan(ctx, **_scan_args(measurement_height=2.0))

        action_zs = [
            c.args[1][2] for c in ctx.board.move.call_args_list
            if c.args[1][2] == HEIGHT_MM + 2.0
        ]
        assert len(action_zs) == 4

    def test_missing_measurement_height_rejected(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        args = _scan_args()
        args.pop("measurement_height")
        with pytest.raises(TypeError, match="measurement_height"):
            scan(ctx, **args)

    def test_missing_interwell_scan_height_rejected(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        args = _scan_args()
        args.pop("interwell_scan_height")
        with pytest.raises(TypeError, match="interwell_scan_height"):
            scan(ctx, **args)

    def test_safe_approach_below_measurement_rejected(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        with pytest.raises(ProtocolExecutionError, match="Approach must be at or above"):
            scan(ctx, **_scan_args(measurement_height=5.0, interwell_scan_height=2.0))

    def test_relative_offsets_and_well_z_passed_to_method_when_supported(self):
        """When the method signature has ``measurement_height`` /
        ``indentation_limit_height`` / ``well_z``, the engine forwards
        the user's relative offsets verbatim and injects ``well_z`` from
        the plate's calibrated well coordinate. The instrument resolves
        absolute Z values internally."""
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()
        ctx.board.gantry = object()

        results = scan(
            ctx, plate="plate_1", instrument="uvvis", method="indentation",
            measurement_height=2.0,
            interwell_scan_height=SAFE_APPROACH,
            indentation_limit_height=-5.0,   # 5 mm into the well at deepest
        )

        for r in results.values():
            assert r["measurement_height"] == 2.0
            assert r["indentation_limit_height"] == -5.0
            assert r["well_z"] == HEIGHT_MM

    def test_legacy_z_limit_rejected_at_runtime(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        with pytest.raises(ProtocolExecutionError, match="z_limit"):
            scan(
                ctx, plate="plate_1", instrument="uvvis", method="indentation",
                measurement_height=MEASUREMENT,
                interwell_scan_height=SAFE_APPROACH,
                method_kwargs={"z_limit": 5.0},
            )

    def test_legacy_interwell_travel_height_rejected(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        with pytest.raises(ProtocolExecutionError, match="interwell_travel_height"):
            scan(
                ctx, plate="plate_1", instrument="uvvis", method="measure",
                measurement_height=MEASUREMENT,
                interwell_scan_height=SAFE_APPROACH,
                method_kwargs={"interwell_travel_height": 5.0},
            )

    def test_returns_dict_of_results_per_well(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        result = scan(ctx, **_scan_args())

        assert set(result.keys()) == {"A1", "A2", "B1", "B2"}
        assert all(v is True for v in result.values())

    def test_captures_false_results(self):
        from protocol_engine.commands.scan import scan

        sensor = _make_sensor()
        sensor._return_value = False
        ctx = _mock_context(sensor=sensor)

        result = scan(ctx, **_scan_args())

        assert all(v is False for v in result.values())

    def test_calls_method_once_per_well(self):
        from protocol_engine.commands.scan import scan

        sensor = _make_sensor()
        ctx = _mock_context(sensor=sensor)

        scan(ctx, **_scan_args())

        assert sensor.call_count == 4

    def test_validates_plate_is_wellplate(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()
        ctx.deck.__getitem__ = MagicMock(return_value=MagicMock(spec=[]))

        with pytest.raises(ProtocolExecutionError, match="WellPlate"):
            scan(ctx, plate="vial_1", instrument="uvvis", method="measure",
                 measurement_height=MEASUREMENT, interwell_scan_height=SAFE_APPROACH)

    def test_unknown_instrument_raises(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        with pytest.raises(ProtocolExecutionError, match="instrument"):
            scan(ctx, plate="plate_1", instrument="nonexistent", method="measure",
                 measurement_height=MEASUREMENT, interwell_scan_height=SAFE_APPROACH)

    def test_unknown_method_raises(self):
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        with pytest.raises(ProtocolExecutionError, match="method"):
            scan(ctx, plate="plate_1", instrument="uvvis", method="nonexistent",
                 measurement_height=MEASUREMENT, interwell_scan_height=SAFE_APPROACH)

    def test_logs_normalized_instrument_measurement(self):
        from protocol_engine.commands.scan import scan

        sensor = _make_sensor()
        sensor._return_value = UVVisSpectrum(
            wavelengths=(400.0, 500.0),
            intensities=(0.1, 0.2),
            integration_time_s=0.24,
        )
        ctx = _mock_context(sensor=sensor)
        ctx.data_store = MagicMock()
        ctx.data_store.get_contents.return_value = []
        ctx.data_store.create_experiment.return_value = 101
        ctx.campaign_id = 77

        scan(ctx, **_scan_args())

        assert ctx.data_store.log_measurement.call_count == 4
        measurement = ctx.data_store.log_measurement.call_args_list[0].args[1]
        assert isinstance(measurement, InstrumentMeasurement)

    def test_delay_sleeps_between_wells(self):
        from unittest.mock import patch
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        with patch("protocol_engine.commands.scan.time.sleep") as mock_sleep:
            scan(ctx, **_scan_args(delay_s=5.0))
            assert mock_sleep.call_count == 3
            mock_sleep.assert_called_with(5.0)

    def test_no_delay_by_default(self):
        from unittest.mock import patch
        from protocol_engine.commands.scan import scan

        ctx = _mock_context()

        with patch("protocol_engine.commands.scan.time.sleep") as mock_sleep:
            scan(ctx, **_scan_args())
            mock_sleep.assert_not_called()
