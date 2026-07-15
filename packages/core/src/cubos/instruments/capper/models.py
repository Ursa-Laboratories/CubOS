"""Value types for capper/decapper instruments."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CapperStatus:
    """Snapshot of capper status returned by ``get_status()``."""

    cap_present: bool
    is_actuating: bool = False

    @property
    def is_valid(self) -> bool:
        return isinstance(self.cap_present, bool)
