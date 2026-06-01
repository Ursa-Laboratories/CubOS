"""Python-native SHARC UV protocol definitions."""

from __future__ import annotations

from protocol_engine import Protocol

from .builder import compile_protocol_steps, protocol_step


def uv_motion_scan_protocol() -> Protocol:
    """Return the SHARC UV motion-only scan protocol as compiled Python objects."""
    return Protocol(
        steps=compile_protocol_steps(
            protocol_step(
                "scan",
                plate="plate_holder.plate",
                instrument="uv_curing",
                method="health_check",
                measurement_height=1.0,
                interwell_scan_height=5.0,
            ),
        ),
    )
