"""Python-native Filmetrics protocol definitions."""

from __future__ import annotations

from protocol_engine import Protocol

from .builder import compile_protocol_steps, protocol_step


def scan_protocol() -> Protocol:
    """Return the Filmetrics scan protocol as compiled Python objects."""
    return Protocol(
        steps=compile_protocol_steps(
            protocol_step(
                "scan",
                plate="plate_1",
                instrument="filmetrics",
                method="measure",
                measurement_height=10.0,
                interwell_scan_height=10.0,
            ),
        ),
    )
