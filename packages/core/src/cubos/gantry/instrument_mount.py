from __future__ import annotations

import logging
import math
from typing import Any, TYPE_CHECKING

from cubos.instruments.base_instrument import BaseInstrument
from cubos.instruments.lighting.interface import LightingInstrument

if TYPE_CHECKING:
    from cubos.gantry import Gantry

# A position is either an (x, y, z) tuple or any object with x, y, z attributes
# (e.g. a labware object sitting at a fixed deck location).
Position = Any


class InstrumentedGantry:
    """Gantry plus the instruments mounted on it.

    Holds one physical Gantry controller and a dictionary of named instruments.
    Each instrument's offset_x, offset_y, and depth describe its mounting
    position relative to the gantry head so runtime motion can calculate the
    gantry pose needed to put an instrument tip at a deck-frame coordinate.
    """

    def __init__(
        self,
        controller: Gantry,
        instruments: dict[str, BaseInstrument] | None = None,
        expected_grbl_settings: dict[str, float] | None = None,
        safe_z: float | None = None,
    ):
        self.controller = controller
        self.instruments: dict[str, BaseInstrument] = instruments or {}
        self.expected_grbl_settings = (
            dict(expected_grbl_settings) if expected_grbl_settings else None
        )
        self.safe_z = safe_z
        self.last_commanded_pose: dict[str, Any] | None = None
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
        travel: the gantry lifts/lowers to it before moving XY, then
        descends/ascends to the target Z. ``move_to_labware`` uses this to
        travel at the gantry's absolute ``safe_z`` between labware.
        """
        instr = self._resolve_instrument(instrument)
        x, y, z = self._resolve_position(position)
        self._validate_finite_xyz(x, y, z, instr.name)
        if travel_z is not None and not math.isfinite(travel_z):
            raise ValueError(
                f"non-finite travel_z={travel_z} for instrument {instr.name!r}."
            )
        depth = self._effective_depth(instr)
        gantry_x = x - instr.offset_x
        gantry_y = y - instr.offset_y
        gantry_z = z + depth
        gantry_travel_z = travel_z + depth if travel_z is not None else None
        self.logger.info(
            "Moving %s to (%.3f, %.3f, %.3f) -> gantry (%.3f, %.3f, %.3f)",
            instr.name, x, y, z, gantry_x, gantry_y, gantry_z,
        )
        self.last_commanded_pose = {
            "instrument": instr.name,
            "instrument_position": (x, y, z),
            "gantry_position": (gantry_x, gantry_y, gantry_z),
            "travel_z": gantry_travel_z,
        }
        self.controller.move_to(
            gantry_x, gantry_y, gantry_z, travel_z=gantry_travel_z,
        )

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
        (``measure``, ``scan``, ...) follow up with a raw ``move`` to
        descend to the per-labware action plane.
        """
        if self.safe_z is None:
            raise ValueError(
                "InstrumentedGantry.safe_z is not set. Configure `cnc.safe_z` "
                "in the gantry YAML or build the InstrumentedGantry with "
                "`safe_z=...`."
            )
        instr = self._resolve_instrument(instrument)
        x, y, z = self._resolve_position(labware)
        self._validate_finite_xyz(x, y, z, instr.name)
        travel_z = self.safe_z
        ceiling = self._gantry_z_ceiling()
        if ceiling is not None:
            # Travel with the carriage at the top of the working volume so
            # every tool mounted on the head — not just the active
            # instrument — clears the deck. safe_z remains the floor and the
            # approach hover plane.
            travel_z = max(travel_z, ceiling - self._effective_depth(instr))
        self.move(instr, (x, y, self.safe_z), travel_z=travel_z)

    def _gantry_z_ceiling(self) -> float | None:
        """Gantry-frame z_max from the controller config, if available."""
        config = getattr(self.controller, 'config', None)
        if not isinstance(config, dict):
            return None
        volume = config.get('working_volume')
        if not isinstance(volume, dict):
            return None
        z_max = volume.get('z_max')
        if isinstance(z_max, (int, float)) and math.isfinite(float(z_max)):
            return float(z_max)
        return None

    def _validate_finite_xyz(self, x: float, y: float, z: float, instr_name: str) -> None:
        for label, value in (("x", x), ("y", y), ("z", z)):
            if not math.isfinite(value):
                raise ValueError(
                    f"non-finite {label}={value} for instrument {instr_name!r}."
                )

    @staticmethod
    def _effective_depth(instr: BaseInstrument) -> float:
        """Read ``instr.effective_depth`` and guard the value as finite."""
        depth = instr.effective_depth
        if not isinstance(depth, (int, float)) or not math.isfinite(depth):
            raise ValueError(
                f"non-finite effective_depth={depth!r} for instrument {instr.name!r}."
            )
        return float(depth)

    def object_position(
        self, obj: str | BaseInstrument | Any,
    ) -> tuple[float, float]:
        """Return the current (x, y) position of an instrument or object."""
        if isinstance(obj, str):
            obj = self._resolve_instrument(obj)

        if isinstance(obj, BaseInstrument):
            coords = self.controller.get_coordinates()
            return (
                coords["x"] + obj.offset_x,
                coords["y"] + obj.offset_y,
            )

        return (obj.x, obj.y)

    def connect_instruments(self) -> None:
        """Connect all mounted instruments."""
        for name, instrument in self.instruments.items():
            self.logger.info("Connecting instrument: %s", name)
            instrument.connect()

    def disconnect_instruments(self) -> None:
        """Disconnect all instruments, logging errors without re-raising.

        Lighting is commanded off first, best-effort, so an aborted run
        never leaves lights on.
        """
        for name, instrument in self.instruments.items():
            if isinstance(instrument, LightingInstrument):
                try:
                    instrument.all_off()
                except Exception:
                    self.logger.exception(
                        "Failed to turn off lighting instrument '%s'", name,
                    )
        for name, instrument in self.instruments.items():
            try:
                self.logger.info("Disconnecting instrument: %s", name)
                instrument.disconnect()
            except Exception:
                self.logger.exception(
                    "Failed to disconnect instrument '%s'", name,
                )

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
