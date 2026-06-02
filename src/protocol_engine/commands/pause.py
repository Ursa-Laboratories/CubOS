"""Protocol commands: pause and breakpoint."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..registry import protocol_command

if TYPE_CHECKING:
    from ..runtime import ProtocolContext


@protocol_command("pause")
def pause(
    context: ProtocolContext,
    seconds: float,
    reason: str = "",
) -> None:
    """Pause protocol execution for a fixed duration.

    Args:
        context: Runtime context.
        seconds: Duration to pause in seconds.
        reason:  Optional reason for the pause (logged).
    """
    msg = f"Pausing for {seconds}s"
    if reason:
        msg += f" ({reason})"
    context.logger.info(msg)
    time.sleep(seconds)


@protocol_command("breakpoint")
def breakpoint_cmd(
    context: ProtocolContext,
    message: str = "Press Enter to continue...",
) -> None:
    """Halt protocol execution until the user presses Enter.

    Args:
        context: Runtime context.
        message: Prompt message displayed to the user.
    """
    context.logger.info("Breakpoint: %s", message)
    input(message)
