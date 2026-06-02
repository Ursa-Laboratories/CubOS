"""Protocol: executable sequence of validated protocol steps."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from deck.deck import Deck

from gantry.instrument_mount import InstrumentedGantry
from gantry.gantry_config import GantryConfig


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
    handler: Callable
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


class Protocol:
    """An executable protocol: a validated, ordered list of steps.

    Usage from YAML::

        protocol = load_protocol_from_yaml("my_protocol.yaml")
        context = ProtocolContext(gantry=gantry, deck=deck)
        protocol.run(context)

    Usage from pure Python (no YAML)::

        from protocol_engine.commands.move import move

        steps = [
            ProtocolStep(
                index=0,
                command_name="move",
                handler=move,
                args={"instrument": "pipette", "position": "plate_1.A1"},
            ),
        ]
        protocol = Protocol(steps=steps)
        protocol.run(context)
    """

    def __init__(
        self,
        steps: List[ProtocolStep],
        source_path: Path | None = None,
        positions: Dict[str, Any] | None = None,
    ) -> None:
        self._steps = list(steps)
        self.source_path = source_path
        self.positions = positions or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    def steps(self) -> List[ProtocolStep]:
        return list(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    def run(self, context: ProtocolContext) -> List[Any]:
        """Execute all steps sequentially. Returns list of step results."""
        self.logger.info(
            "Running protocol (%d steps)%s",
            len(self._steps),
            f" from {self.source_path}" if self.source_path else "",
        )
        results: List[Any] = []
        for step in self._steps:
            result = step.execute(context)
            results.append(result)
        self.logger.info("Protocol complete.")
        return results

    def __repr__(self) -> str:
        cmds = ", ".join(s.command_name for s in self._steps)
        return f"Protocol([{cmds}])"
