from abc import ABC, abstractmethod
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class InstrumentError(Exception):
    """Base exception for all instrument errors."""
    pass


class BaseInstrument(ABC):
    """Abstract base class for all instruments.

    All instruments accept an ``offline`` flag. When True, connect/disconnect
    are no-ops, health_check returns True, and instrument-specific methods
    return synthetic data without touching hardware.

    Z semantics
    -----------
    CubOS uses a +Z-up deck frame.

    Instruments don't carry labware-relative motion heights. The protocol
    commands own them:

    * ``measurement_height`` (action plane, labware-relative offset) is a
      first-class argument to ``measure`` and ``scan``.
    * ``interwell_scan_height`` (between-wells XY-travel offset) is a
      first-class argument to ``scan``.

    Inter-labware travel and the entry approach for the first well of a
    scan use the gantry-level ``safe_z`` (absolute deck-frame Z).
    """

    def __init__(
        self,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
    ):
        self.name = name or self.__class__.__name__
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.depth = depth
        self._offline = offline
        self.logger = logging.getLogger(f"{__name__}.{self.name}")

    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass

    def warm_up(self) -> None:
        pass

    def calibrate(self) -> None:
        pass

    def handle_error(self, error: Exception, context: str = "") -> None:
        msg = f"Error in {self.name}{f' ({context})' if context else ''}: {str(error)}"
        self.logger.error(msg)
        if isinstance(error, InstrumentError):
            raise error
        raise InstrumentError(msg) from error
