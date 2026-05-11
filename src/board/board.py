from __future__ import annotations

import logging
import math
from typing import Any, TYPE_CHECKING

from instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from gantry import Gantry

# A position is either an (x, y, z) tuple or any object with x, y, z attributes
# (e.g. a labware object sitting at a fixed deck location).
Position = Any


class Board:
    """Physical board layout: a gantry and the instruments mounted on it.

    Holds a single Gantry instance and a dictionary of named instruments.
    Each instrument's offset_x, offset_y, and depth describe its position
    relative to the router so the board can calculate absolute positions
    in CubOS deck-frame coordinates.
    """

    def __init__(
        self,
        gantry: Gantry,
        instruments: dict[str, BaseInstrument] | None = None,
        expected_grbl_settings: dict[str, float] | None = None,
        safe_z: float | None = None,
    ):
        self.gantry = gantry
        self.instruments: dict[str, BaseInstrument] = instruments or {}
        self.expected_grbl_settings = (
            dict(expected_grbl_settings) if expected_grbl_settings else None
        )
        self.safe_z = safe_z
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def move(
        self,
        instrument: str | BaseInstrument,
        position: Position,
        travel_z: float | None = None,
    ) -> None:
        """Move the gantry so that *instrument* arrives at *position*.

        Accounts for the instrument's offset_x, offset_y, and depth so the
        gantry head ends up at the right place for the instrument tip to be
        at the requested (x, y, z). Validates that the target is finite
        (no NaN/Inf) before commanding the gantry.

        ``travel_z``, if given, is an instrument-tip Z held during XY
        travel — the gantry lifts/lowers to it before moving XY, then
        descends/ascends to the target Z. ``Board.move_to_labware`` uses
        this to travel at the gantry's absolute ``safe_z`` between
        labware.

        Args:
            instrument: Name (key in ``self.instruments``) or instance.
            position:   (x, y, z) tuple or labware object with x, y, z attrs.
            travel_z:   Instrument-tip Z to hold during XY travel, in the
                        same user space as ``position.z``.
        """
        instr = self._resolve_instrument(instrument)
        x, y, z = self._resolve_position(position)
        self._validate_finite_xyz(x, y, z, instr.name)
        if travel_z is not None and not math.isfinite(travel_z):
            raise ValueError(
                f"non-finite travel_z={travel_z} for instrument {instr.name!r}."
            )
        gantry_x = x - instr.offset_x
        gantry_y = y - instr.offset_y
        gantry_z = z + instr.depth
        gantry_travel_z = (
            travel_z + instr.depth if travel_z is not None else None
        )
        self.logger.info(
            "Moving %s to (%.3f, %.3f, %.3f) → gantry (%.3f, %.3f, %.3f)",
            instr.name, x, y, z, gantry_x, gantry_y, gantry_z,
        )
        self.gantry.move_to(gantry_x, gantry_y, gantry_z, travel_z=gantry_travel_z)

    def move_to_labware(
        self,
        instrument: str | BaseInstrument,
        labware: Position,
    ) -> None:
        """Travel *instrument* to ``safe_z`` above a labware target.

        Emits a single ``move`` with ``travel_z = self.safe_z``: the
        gantry lifts/lowers to that absolute deck-frame Z plane at
        the current XY, travels XY at ``safe_z``, and ends above the
        target without descending. Higher-level commands
        (``measure``, ``scan``, ...) follow up with a raw ``board.move``
        to descend to the per-labware action plane.

        Args:
            instrument: Name or instance.
            labware:    A labware-reference point — anything with x/y/z
                        attributes (e.g. a ``Coordinate3D`` returned by
                        ``Deck.resolve_coordinate()``). ``(x, y, z)`` tuples are
                        accepted for convenience/testing.

        Raises:
            ValueError: If ``self.safe_z`` is not configured.
        """
        if self.safe_z is None:
            raise ValueError(
                "Board.safe_z is not set. Configure `cnc.safe_z` in the "
                "gantry YAML or build the Board with `safe_z=...`."
            )
        instr = self._resolve_instrument(instrument)
        x, y, z = self._resolve_position(labware)
        self._validate_finite_xyz(x, y, z, instr.name)
        self.move(instr, (x, y, self.safe_z), travel_z=self.safe_z)

    def _validate_finite_xyz(self, x: float, y: float, z: float, instr_name: str) -> None:
        for label, value in (("x", x), ("y", y), ("z", z)):
            if not math.isfinite(value):
                raise ValueError(
                    f"non-finite {label}={value} for instrument {instr_name!r}."
                )

    def object_position(
        self, obj: str | BaseInstrument | Any,
    ) -> tuple[float, float]:
        """Return the current (x, y) position of an object on the board.

        For instruments (str key or BaseInstrument): computes position from
        the current gantry coordinates plus the instrument's offset.

        For labware or other objects: reads ``obj.x`` and ``obj.y`` directly
        (the object is assumed to have a fixed deck position).

        Args:
            obj: Instrument name, BaseInstrument instance, or any object
                 with ``x`` and ``y`` attributes.

        Returns:
            (x, y) tuple of the object's current position.
        """
        if isinstance(obj, str):
            obj = self._resolve_instrument(obj)

        if isinstance(obj, BaseInstrument):
            coords = self.gantry.get_coordinates()
            return (
                coords["x"] + obj.offset_x,
                coords["y"] + obj.offset_y,
            )

        return (obj.x, obj.y)

    # ── Instrument lifecycle ─────────────────────────────────────────────

    def connect_instruments(self) -> None:
        """Connect all instruments on the board."""
        for name, instrument in self.instruments.items():
            self.logger.info("Connecting instrument: %s", name)
            instrument.connect()

    def disconnect_instruments(self) -> None:
        """Disconnect all instruments, logging errors without re-raising.

        Ensures every instrument gets a disconnect attempt even if one fails.
        """
        for name, instrument in self.instruments.items():
            try:
                self.logger.info("Disconnecting instrument: %s", name)
                instrument.disconnect()
            except Exception:
                self.logger.exception(
                    "Failed to disconnect instrument '%s'", name,
                )

    # ── Private helpers ───────────────────────────────────────────────────

    def _resolve_instrument(
        self, instrument: str | BaseInstrument,
    ) -> BaseInstrument:
        """Look up an instrument by name or return it directly."""
        if isinstance(instrument, str):
            if instrument not in self.instruments:
                raise KeyError(
                    f"Unknown instrument '{instrument}'. "
                    f"Available: {', '.join(sorted(self.instruments.keys()))}"
                )
            return self.instruments[instrument]
        return instrument

    @staticmethod
    def _resolve_position(position: Position) -> tuple[float, float, float]:
        """Convert a position tuple or labware object to (x, y, z)."""
        if isinstance(position, tuple):
            return position
        return (position.x, position.y, position.z)
