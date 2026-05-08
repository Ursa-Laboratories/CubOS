"""End-to-end integration tests for the DataStore persistence layer."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

from data.data_store import DataStore
from deck.labware.labware import Coordinate3D
from deck.labware.vial import Vial
from deck.labware.well_plate import WellPlate
from instruments.base_instrument import BaseInstrument
from instruments.uvvis_ccs.models import UVVisSpectrum
from protocol_engine.commands.pipette import transfer
from protocol_engine.commands.scan import scan
from protocol_engine.protocol import ProtocolContext


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_plate() -> WellPlate:
    return WellPlate(
        name="plate_1",
        model_name="test_96",
        length=127.71,
        width=85.43,
        height=14.10,
        rows=2,
        columns=2,
        wells={
            "A1": Coordinate3D(x=0.0, y=0.0, z=75.0),
            "A2": Coordinate3D(x=10.0, y=0.0, z=75.0),
            "B1": Coordinate3D(x=0.0, y=8.0, z=75.0),
            "B2": Coordinate3D(x=10.0, y=8.0, z=75.0),
        },
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


def _make_vial() -> Vial:
    return Vial(
        name="reagent_vial",
        model_name="test_vial",
        height=50.0,
        diameter=20.0,
        location=Coordinate3D(x=50.0, y=0.0, z=0.0),
        capacity_ul=5000.0,
        working_volume_ul=4000.0,
    )


class _FakeUVVis(BaseInstrument):
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def measure(self) -> UVVisSpectrum:
        return UVVisSpectrum(
            wavelengths=(500.0, 501.0, 502.0),
            intensities=(0.1, 0.2, 0.3),
            integration_time_s=0.24,
        )


# ─── Full protocol run with DataStore ────────────────────────────────────────


class TestFullProtocolWithDataStore:

    def test_transfer_then_scan_persists_all_rows(self):
        plate = _make_plate()
        vial = _make_vial()
        labware_map = {"plate_1": plate, "reagent_vial": vial}

        sensor = _FakeUVVis(
            name="uvvis", offset_x=0.0, offset_y=0.0, depth=0.0,
        )
        pipette = MagicMock()

        board = MagicMock()
        board.instruments = {"uvvis": sensor, "pipette": pipette}

        deck = MagicMock()
        deck.__getitem__ = MagicMock(side_effect=lambda k: labware_map[k])
        deck.resolve = MagicMock(return_value=(0.0, 0.0, 0.0))

        store = DataStore(db_path=":memory:")
        cid = store.create_campaign(
            description="integration test",
            deck_config="configs/deck.yaml",
            protocol_config="configs/protocol.yaml",
        )
        store.register_labware(cid, "plate_1", plate)
        store.register_labware(cid, "reagent_vial", vial)

        ctx = ProtocolContext(
            board=board,
            deck=deck,
            logger=logging.getLogger("integration"),
            data_store=store,
            campaign_id=cid,
        )

        # Step 1: Transfer reagent into A1 and B1
        transfer(ctx, source="reagent_vial", destination="plate_1.A1", volume_ul=50.0)
        transfer(ctx, source="reagent_vial", destination="plate_1.B1", volume_ul=75.0)

        # Verify DB labware tracking
        contents_a1 = store.get_contents(cid, "plate_1", "A1")
        assert len(contents_a1) == 1
        assert contents_a1[0]["source"] == "reagent_vial"

        contents_b1 = store.get_contents(cid, "plate_1", "B1")
        assert len(contents_b1) == 1

        # Step 2: Scan entire plate
        results = scan(ctx, plate="plate_1", instrument="uvvis", method="measure", measurement_height=0.0, interwell_scan_height=10.0)
        assert len(results) == 4

        # Verify DB rows
        campaigns = store._conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
        assert campaigns == 1

        experiments = store._conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        assert experiments == 4  # 4 scan wells

        uvvis_count = store._conn.execute(
            "SELECT COUNT(*) FROM uvvis_measurements"
        ).fetchone()[0]
        assert uvvis_count == 4

        # Verify contents snapshot for A1 scan experiment includes the transfer
        a1_exp = store._conn.execute(
            "SELECT contents FROM experiments WHERE labware_name = 'plate_1' AND well_id = 'A1'"
        ).fetchone()
        parsed = json.loads(a1_exp[0])
        assert len(parsed) == 1
        assert parsed[0]["source"] == "reagent_vial"

        # Verify labware volume tracking
        row = store._conn.execute(
            "SELECT current_volume_ul FROM labware "
            "WHERE campaign_id = ? AND labware_key = 'plate_1' AND well_id = 'A1'",
            (cid,),
        ).fetchone()
        assert row[0] == 50.0

        store.close()


# ─── Full protocol run without DataStore ─────────────────────────────────────


class TestFullProtocolWithoutDataStore:

    def test_no_regressions_when_data_store_is_none(self):
        plate = _make_plate()
        vial = _make_vial()
        labware_map = {"plate_1": plate, "reagent_vial": vial}

        sensor = _FakeUVVis(
            name="uvvis", offset_x=0.0, offset_y=0.0, depth=0.0,
        )
        pipette = MagicMock()

        board = MagicMock()
        board.instruments = {"uvvis": sensor, "pipette": pipette}

        deck = MagicMock()
        deck.__getitem__ = MagicMock(side_effect=lambda k: labware_map[k])
        deck.resolve = MagicMock(return_value=(0.0, 0.0, 0.0))

        ctx = ProtocolContext(
            board=board,
            deck=deck,
            logger=logging.getLogger("integration_no_store"),
        )

        transfer(ctx, source="reagent_vial", destination="plate_1.A1", volume_ul=50.0)
        results = scan(ctx, plate="plate_1", instrument="uvvis", method="measure", measurement_height=0.0, interwell_scan_height=10.0)

        assert len(results) == 4
        assert all(isinstance(v, UVVisSpectrum) for v in results.values())
