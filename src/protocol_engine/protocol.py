"""Protocol: executable sequence of validated protocol steps."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .runtime import ProtocolContext, ProtocolStep


@dataclass(frozen=True)
class ProtocolSetup:
    """Gantry/deck pairing a Python-authored protocol carries for hardware runs.

    YAML-loaded protocols have no setup metadata unless explicitly wrapped
    later; only protocols built via ``ProtocolBuilder.with_setup(...)`` know
    which machine and deck they belong to.
    """

    gantry_path: str | Path
    deck_path: str | Path


class Protocol:
    """An executable protocol: a validated, ordered list of steps.

    Two execution entry points sit at different layers:

    ``execute(context)`` is the low-level primitive — it runs the steps
    against an already-prepared :class:`ProtocolContext` and owns no
    hardware lifecycle::

        protocol = load_protocol_from_yaml("my_protocol.yaml")
        context = ProtocolContext(gantry=gantry, deck=deck)
        protocol.execute(context)

    ``run()`` is the high-level, user-facing entry point. It requires setup
    metadata and owns the full hardware session (connect, prepare, execute,
    cleanup), delegating step execution to ``execute(context)``::

        protocol = (
            ProtocolBuilder.with_setup(gantry_path=..., deck_path=...)
            .add_home()
            .add_move(instrument="asmi", position="plate.A1")
            .build()
        )
        protocol.validate()   # offline check, no hardware
        protocol.run()        # full hardware session
    """

    def __init__(
        self,
        steps: List[ProtocolStep],
        source_path: Path | None = None,
        positions: Dict[str, Any] | None = None,
        setup: ProtocolSetup | None = None,
    ) -> None:
        self._steps = list(steps)
        self.source_path = source_path
        self.positions = positions or {}
        self.setup = setup
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    def steps(self) -> List[ProtocolStep]:
        return list(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    def execute(self, context: ProtocolContext) -> List[Any]:
        """Execute all steps sequentially against a prepared context.

        Low-level primitive: the caller owns the gantry connection and
        instrument lifecycle. Returns the list of step results.
        """
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

    def validate(self) -> None:
        """Validate the protocol offline against its setup metadata.

        Runs the same gantry/deck loading, bounds, and semantic validation as
        a hardware run, but with an offline gantry — it never connects to
        hardware and never executes any steps.

        Raises:
            ValueError: If the protocol has no setup metadata.
        """
        if self.setup is None:
            raise ValueError(
                "Protocol has no setup metadata to validate against. Build it "
                "with ProtocolBuilder.with_setup(gantry_path=..., deck_path=...) "
                "before calling validate()."
            )
        from .setup import setup_protocol

        setup_protocol(
            self.setup.gantry_path,
            self.setup.deck_path,
            self,
            mock_mode=True,
        )

    def run(
        self,
        campaign: str | None = None,
        data_store: Any | None = None,
        protocol_config: str | None = None,
    ) -> List[Any]:
        """Run the protocol on hardware as a full session.

        High-level, user-facing entry point: requires setup metadata and runs
        the full hardware lifecycle (load gantry, connect, prepare, connect
        instruments, health check, execute, disconnect).

        Data persistence is opt-in by naming a campaign. With ``campaign``
        given, measurements are saved: a campaign is created (recording this
        protocol's own gantry/deck paths from its setup metadata) and the run
        writes to it. Without ``campaign``, nothing is persisted.

        Args:
            campaign: Campaign description. When set, measurements are saved.
            data_store: Optional :class:`data.DataStore` to write into. When
                omitted (and ``campaign`` is set), a default store is created
                and closed automatically.
            protocol_config: Optional identifier recorded on the campaign for
                the source that built this protocol (e.g. a module path).

        Raises:
            ValueError: If the protocol has no setup metadata, or if a
                persistence argument is given without ``campaign``.
        """
        if self.setup is None:
            raise ValueError(
                "Protocol.run() needs setup metadata to drive hardware. Build "
                "it with ProtocolBuilder.with_setup(gantry_path=..., "
                "deck_path=...), or call execute(context) with a prepared "
                "context."
            )

        from .setup import run_on_hardware

        if campaign is None:
            if data_store is not None or protocol_config is not None:
                raise ValueError(
                    "Pass campaign=\"...\" to persist measurements; "
                    "data_store/protocol_config require a named campaign."
                )
            return run_on_hardware(
                self.setup.gantry_path,
                self.setup.deck_path,
                self,
            )

        from data import DataStore

        owns_store = data_store is None
        store = data_store if data_store is not None else DataStore()
        try:
            campaign_id = store.create_campaign(
                campaign,
                gantry_config=str(self.setup.gantry_path),
                deck_config=str(self.setup.deck_path),
                protocol_config=protocol_config,
            )
            return run_on_hardware(
                self.setup.gantry_path,
                self.setup.deck_path,
                self,
                data_store=store,
                campaign_id=campaign_id,
            )
        finally:
            if owns_store:
                store.close()

    def __repr__(self) -> str:
        cmds = ", ".join(s.command_name for s in self._steps)
        return f"Protocol([{cmds}])"
