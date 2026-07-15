"""Conflict record used by the PANDA-BEAR importer's detection/resolution report.

Two severities:

* ``"conflict"`` -- a row-selection ambiguity (duplicate vials, a tip rack
  whose declared shape doesn't match its actual tips, a tip rack with zero
  actual tips, a missing physical constant, or a well-plate height source
  disagreement). Blocks the import (non-zero exit, no files written) unless
  covered by the resolutions file.
* ``"warning"`` -- a positional/geometric observation (out-of-envelope
  coordinates, well-grid pitch residuals, vial content/volume mismatches).
  Always reported, never blocking -- exact physical positions are expected
  to be re-derived after labware is moved and the controller is verified.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Conflict:
    category: str
    severity: str  # "conflict" | "warning"
    row_ids: tuple[int, ...]
    message: str
    resolved: bool
    resolution: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in ("conflict", "warning"):
            raise ValueError(f"Unknown conflict severity: {self.severity!r}")
        if self.severity == "warning" and not self.resolved:
            raise ValueError("Warning-severity conflicts must be marked resolved (non-blocking).")

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "row_ids": list(self.row_ids),
            "message": self.message,
            "resolved": self.resolved,
            "resolution": self.resolution,
        }


def sort_key(conflict: Conflict) -> tuple:
    return (conflict.category, conflict.row_ids, conflict.message)
