"""Protocol: executable sequence of validated protocol steps."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from .runtime import ProtocolContext, ProtocolStep


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
