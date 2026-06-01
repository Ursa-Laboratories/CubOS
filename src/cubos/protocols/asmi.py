"""Python-native ASMI protocol definitions."""

from __future__ import annotations

from protocol_engine import Protocol

from .builder import compile_protocol_steps, protocol_step

def move_a1_protocol() -> Protocol:
    """Return the ASMI A1 move protocol as compiled Python objects."""
    return Protocol(
        steps=compile_protocol_steps(
            protocol_step("home"),
            protocol_step(
                "move",
                instrument="asmi",
                position="plate.A1",
            ),
        ),
    )
