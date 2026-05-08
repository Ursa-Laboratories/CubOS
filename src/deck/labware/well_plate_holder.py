from __future__ import annotations

from .holder import HolderLabware
from .labware import Coordinate3D


class WellPlateHolder(HolderLabware):
    """Holder for a single well plate or slide-mounted plate assembly."""

    model_name: str = "SlideHolder_Top"
    length: float = 100.0
    width: float = 155.0
    height: float = 14.8
    labware_support_height: float = 10.0
    labware_seat_height_from_bottom: float = 5.0

    def get_plate_slot(self, slot_id: str = "plate") -> Coordinate3D:
        return self.get_slot(slot_id)
