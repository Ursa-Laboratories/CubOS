"""Python-native Sterling protocol definitions."""

from __future__ import annotations

from protocol_engine import Protocol

from .builder import compile_protocol_steps, protocol_step

PARK_POSITION = [280.0, 280.0, 85.0]
VIAL_SCAN_POSITIONS = {
    "vial_1_scan": [223.0, 25.0, 40.0],
    "vial_2_scan": [223.0, 58.5, 40.0],
    "vial_3_scan": [223.0, 92.0, 40.0],
    "vial_4_scan": [223.0, 125.5, 40.0],
    "vial_5_scan": [223.0, 159.0, 40.0],
    "vial_6_scan": [223.0, 192.5, 40.0],
    "vial_7_scan": [223.0, 226.0, 40.0],
    "vial_8_scan": [223.0, 259.5, 40.0],
}
VIAL_SCAN_ORDER = (
    "vial_1_scan",
    "vial_8_scan",
    "vial_2_scan",
    "vial_7_scan",
    "vial_3_scan",
    "vial_6_scan",
    "vial_4_scan",
    "vial_5_scan",
)


def vial_scan_protocol() -> Protocol:
    """Return the Sterling vial-position scan as compiled Python objects."""
    return Protocol(
        steps=compile_protocol_steps(
            protocol_step("home"),
            protocol_step(
                "move",
                instrument="potentiostat",
                position="park_position",
                travel_z=85.0,
            ),
            *[
                protocol_step(
                    "move",
                    instrument="potentiostat",
                    position=position,
                    travel_z=85.0,
                )
                for position in VIAL_SCAN_ORDER
            ],
            protocol_step(
                "move",
                instrument="potentiostat",
                position="park_position",
                travel_z=85.0,
            ),
            protocol_step("home"),
        ),
        positions={"park_position": PARK_POSITION, **VIAL_SCAN_POSITIONS},
    )
