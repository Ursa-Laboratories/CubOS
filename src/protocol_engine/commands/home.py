"""Protocol command: home the gantry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..registry import protocol_command

if TYPE_CHECKING:
    from ..protocol import ProtocolContext


@protocol_command("home")
def home(context: "ProtocolContext") -> None:
    """Home the gantry without redefining a calibrated deck-origin WCS.

    Deck-origin configs rely on persistent G54 WPos established by the
    calibration script. This command intentionally does not apply ``G92`` or
    otherwise rewrite work coordinates after homing.

    Args:
        context: Runtime context (board, deck, logger).
    """
    context.logger.info("home: homing gantry")
    gantry = context.board.gantry
    gantry.set_serial_timeout(10)
    try:
        gantry.home()
    finally:
        gantry.set_serial_timeout(0.05)
