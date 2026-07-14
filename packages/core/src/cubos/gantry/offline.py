"""Offline gantry stub for validation and testing without hardware."""

from __future__ import annotations


class OfflineGantry:
    """Stub gantry for offline validation and testing.

    Provides the same interface as Gantry but does nothing—no serial
    connection, no hardware movement.  Used by ``setup_protocol()``
    when no real gantry is provided, and by mock/dry-run modes in
    downstream projects like ASMI_new.
    """

    def __init__(self):
        self._coords = {"x": 0.0, "y": 0.0, "z": 0.0}

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def is_healthy(self) -> bool:
        return True

    def home(self) -> None:
        pass

    def unlock(self) -> None:
        pass

    def move_to(
        self,
        x: float,
        y: float,
        z: float,
        travel_z: float | None = None,
    ) -> None:
        self._coords = {"x": x, "y": y, "z": z}

    def get_coordinates(self) -> dict[str, float]:
        return dict(self._coords)

    def get_status(self) -> str:
        return "Idle"

    def stop(self) -> None:
        pass

    def feed_hold_realtime(self) -> None:
        pass

    def resume(self) -> None:
        pass
