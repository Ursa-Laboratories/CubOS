"""Protocol command: control imaging/deck lighting channels.

Built entirely on the vendor-agnostic
``cubos.instruments.lighting.interface.LightingInstrument`` surface — no
vendor-specific behavior (Arduino command IDs, channel-to-command mapping)
appears here; see ``cubos.instruments.lighting.vendors.pawduino`` for that.

Lights the protocol turns on, the protocol (or its teardown) turns off:
``InstrumentedGantry.disconnect_instruments`` calls ``all_off`` best-effort
on every lighting instrument, so a failed run never leaves the contact
lights baking a sample.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cubos.instruments.lighting.exceptions import LightingError
from cubos.instruments.lighting.interface import LightingInstrument

from ..errors import ProtocolExecutionError
from ..registry import protocol_command
from . import _summaries

if TYPE_CHECKING:
    from ..runtime import ProtocolContext


def _get_lighting(
    context: "ProtocolContext", instrument: str,
) -> LightingInstrument:
    try:
        lighting = context.gantry.instruments[instrument]
    except KeyError as exc:
        raise ProtocolExecutionError(
            f"No instrument {instrument!r} registered on the gantry."
        ) from exc
    if not isinstance(lighting, LightingInstrument):
        raise ProtocolExecutionError(
            f"Instrument {instrument!r} is a {type(lighting).__name__}, not a "
            "LightingInstrument. set_lights requires a `lighting` type "
            "instrument."
        )
    return lighting


@protocol_command("set_lights", summary=_summaries.set_lights)
def set_lights(
    context: "ProtocolContext",
    instrument: str,
    channel: str | None = None,
    brightness: int | None = None,
    all_off: bool = False,
) -> None:
    """Set one lighting channel, or turn everything off.

    Two mutually exclusive forms:

    * ``channel`` + ``brightness`` — turn *channel* on at *brightness*
      percent (an exact level from the vendor's supported set; ``0`` turns
      just that channel off).
    * ``all_off: true`` — turn every channel off. (Named ``all_off`` rather
      than ``off`` because YAML 1.1 parses a bare ``off:`` key as the
      boolean ``false``, not a string.)

    Args:
        context:    Runtime context (instrumented gantry, deck, logger).
        instrument: Name of the lighting instrument registered on the gantry.
        channel:    Channel name, e.g. ``white`` or ``contact``.
        brightness: Brightness percent; must be a level the channel supports.
        all_off:    Turn all channels off instead.
    """
    lighting = _get_lighting(context, instrument)
    if all_off:
        if channel is not None or brightness is not None:
            raise ProtocolExecutionError(
                "set_lights: `all_off: true` cannot be combined with "
                "channel/brightness — use one form or the other."
            )
        try:
            lighting.all_off()
        except LightingError as exc:
            raise ProtocolExecutionError(f"set_lights: {exc}") from exc
        return

    if channel is None or brightness is None:
        raise ProtocolExecutionError(
            "set_lights requires either `all_off: true` or both `channel` "
            "and `brightness`."
        )
    try:
        lighting.set_channel(channel, brightness)
    except LightingError as exc:
        raise ProtocolExecutionError(f"set_lights: {exc}") from exc
