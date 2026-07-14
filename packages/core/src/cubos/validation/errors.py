"""Validation error types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple


@dataclass(frozen=True)
class BoundsViolation:
    """One position that falls outside the gantry working volume."""

    labware_key: str
    position_id: str
    instrument_name: Optional[str]
    coordinate_type: Literal["deck", "gantry"]
    x: float
    y: float
    z: float
    axis: Literal["x", "y", "z"]
    bound_name: str
    bound_value: float


class SetupValidationError(Exception):
    """Raised when protocol setup validation detects bounds violations."""

    def __init__(self, violations: list[BoundsViolation]) -> None:
        self.violations: Tuple[BoundsViolation, ...] = tuple(violations)
        messages = []
        for v in self.violations:
            instr_prefix = f"instrument '{v.instrument_name}' at " if v.instrument_name else ""
            messages.append(
                f"  {v.coordinate_type} position ({v.x}, {v.y}, {v.z}) for "
                f"{instr_prefix}{v.labware_key}.{v.position_id} "
                f"violates {v.bound_name}={v.bound_value}"
            )
        super().__init__(
            f"Bounds validation failed with {len(self.violations)} violation(s):\n"
            + "\n".join(messages)
        )


@dataclass(frozen=True)
class ProtocolSemanticViolation:
    """One protocol step with internally inconsistent runtime semantics."""

    step_index: int
    command_name: str
    message: str


class ProtocolSemanticValidationError(Exception):
    """Raised when setup detects unsafe or contradictory protocol semantics."""

    def __init__(self, violations: list[ProtocolSemanticViolation]) -> None:
        self.violations: Tuple[ProtocolSemanticViolation, ...] = tuple(violations)
        messages = [
            f"  step {v.step_index} ({v.command_name}): {v.message}"
            for v in self.violations
        ]
        super().__init__(
            f"Protocol semantic validation failed with "
            f"{len(self.violations)} violation(s):\n" + "\n".join(messages)
        )
