"""Runtime types shared by executable protocol commands."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from cubos.deck.deck import Deck
from cubos.gantry.gantry_config import GantryConfig
from cubos.gantry.instrument_mount import InstrumentedGantry


@dataclass
class ProtocolContext:
    """Runtime context injected into every command handler.

    Provides access to the instrumented gantry and the Deck
    (labware target resolution).  Optionally carries a DataStore for
    persisting measurements and a campaign_id for the current run.
    """

    gantry: InstrumentedGantry
    deck: Deck
    positions: Dict[str, Any] = field(default_factory=dict)
    gantry_config: Optional[GantryConfig] = None
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("protocol"),
    )
    data_store: Any = None
    campaign_id: int | None = None


@dataclass
class ProtocolStep:
    """One compiled, executable protocol step."""

    index: int
    command_name: str
    handler: Callable[..., Any]
    args: Dict[str, Any]

    def execute(self, context: ProtocolContext) -> Any:
        """Run this step, passing *context* and unpacked *args* to the handler."""
        context.logger.info(
            "Step %d: %s(%s)",
            self.index,
            self.command_name,
            ", ".join(f"{k}={v!r}" for k, v in self.args.items()),
        )
        return self.handler(context, **self.args)
