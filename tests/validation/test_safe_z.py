"""``safe_z`` ceiling validation for measure/scan motion.

``safe_z`` is the absolute deck-frame Z used for inter-labware travel and
the entry approach for the first well of a scan. All resolved approach
and action Z values must satisfy ``z <= safe_z`` so the gantry can
retract above them.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from board.board import Board
from deck.deck import Deck
from deck.labware.labware import Coordinate3D
from deck.labware.well_plate import WellPlate
from gantry.gantry_config import GantryConfig, GantryType, HomingStrategy, WorkingVolume
from protocol_engine.protocol import Protocol, ProtocolStep
from validation.protocol_semantics import validate_protocol_semantics


def _gantry(safe_z: float = 85.0) -> GantryConfig:
    return GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=100.0,
        working_volume=WorkingVolume(
            x_min=0.0, x_max=400.0,
            y_min=0.0, y_max=300.0,
            z_min=0.0, z_max=100.0,
        ),
        safe_z=safe_z,
    )


def _deck() -> Deck:
    return Deck({
        "plate": WellPlate(
            name="plate",
            model_name="test_plate",
            length=127.71,
            width=85.43,
            height=14.10,
            rows=1,
            columns=1,
            wells={"A1": Coordinate3D(x=100.0, y=100.0, z=14.10)},
            capacity_ul=200.0,
            working_volume_ul=150.0,
        )
    })


def _board() -> Board:
    instrument = MagicMock()
    instrument.name = "asmi"
    instrument.offset_x = 0.0
    instrument.offset_y = 0.0
    instrument.depth = 0.0
    return Board(gantry=MagicMock(), instruments={"asmi": instrument})


def _scan(interwell_scan_height: float, measurement_height: float = -1.0) -> Protocol:
    return Protocol([
        ProtocolStep(
            index=0,
            command_name="scan",
            handler=lambda *a, **k: None,
            args={
                "plate": "plate",
                "instrument": "asmi",
                "method": "indentation",
                "measurement_height": measurement_height,
                "interwell_scan_height": interwell_scan_height,
                "indentation_limit_height": -5.0,
                "method_kwargs": {"step_size": 0.1},
            },
        )
    ])


def test_scan_approach_above_safe_z_violates():
    """height=14.10 + interwell_scan_height=80 = 94.10 > safe_z=85."""
    violations = validate_protocol_semantics(
        _scan(interwell_scan_height=80.0),
        _board(), _deck(), _gantry(safe_z=85.0),
    )

    assert any("safe_z" in v.message for v in violations)


def test_scan_approach_at_safe_z_passes():
    """height=14.10 + interwell_scan_height=70.9 = 85.0 == safe_z."""
    assert validate_protocol_semantics(
        _scan(interwell_scan_height=70.9),
        _board(), _deck(), _gantry(safe_z=85.0),
    ) == []


def test_scan_passes_when_safe_z_unconfigured():
    """Without a configured safe_z, the ceiling check is skipped."""
    gantry = GantryConfig(
        serial_port="/dev/ttyUSB0",
        gantry_type=GantryType.CUB_XL,
        homing_strategy=HomingStrategy.STANDARD,
        total_z_range=100.0,
        working_volume=WorkingVolume(
            x_min=0.0, x_max=400.0,
            y_min=0.0, y_max=300.0,
            z_min=0.0, z_max=200.0,
        ),
    )
    assert validate_protocol_semantics(
        _scan(interwell_scan_height=70.0),
        _board(), _deck(), gantry,
    ) == []
