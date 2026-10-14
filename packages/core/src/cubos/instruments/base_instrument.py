from abc import ABC, abstractmethod
from typing import Optional
import logging
import math


class InstrumentError(Exception):
    """Base exception for all instrument errors."""
    pass


class BaseInstrument(ABC):
    """Instrument identity, mounting geometry, and hardware lifecycle.

    ``offline=True`` disables hardware access. Labware-relative action heights
    belong to protocol commands; instruments carry only mounting offsets.
    """

    def __init__(
        self,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
    ):
        for field, value in (("offset_x", offset_x), ("offset_y", offset_y), ("depth", depth)):
            if not math.isfinite(value):
                raise ValueError(f"{field} must be finite, got {value!r}.")
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

    @property
    def effective_depth(self) -> float:
        """Currently active depth from the gantry head to the tool tip.

        Defaults to the static ``depth``. Subclasses override when a
        runtime attachment (e.g. a disposable pipette tip) extends the
        tool below the bare nozzle.
        """
        return self.depth

    def handle_error(self, error: Exception, context: str = "") -> None:
        msg = f"Error in {self.name}{f' ({context})' if context else ''}: {str(error)}"
        self.logger.error(msg)
        if isinstance(error, InstrumentError):
            raise error
        raise InstrumentError(msg) from error
