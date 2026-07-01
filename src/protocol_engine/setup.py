"""Protocol setup: load all configs, validate, and return a ready-to-run protocol."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)

import yaml

from deck.deck import Deck
from deck.loader import load_deck_from_yaml_safe
from gantry.errors import GantryLoaderError
from gantry.gantry import Gantry
from gantry.gantry_config import GantryConfig
from gantry.instrument_loader import load_instrumented_gantry_from_config
from gantry.instrument_mount import InstrumentedGantry
from gantry.loader import load_gantry_from_yaml_safe
from gantry.origin import validate_deck_origin_minima
from protocol_engine.errors import GantryHealthCheckError
from protocol_engine.loader import load_protocol_from_yaml_safe
from protocol_engine.protocol import Protocol
from protocol_engine.runtime import ProtocolContext
from validation.bounds import validate_protocol_motion_bounds
from validation.errors import ProtocolSemanticValidationError, SetupValidationError
from validation.protocol_semantics import validate_protocol_semantics

ProtocolInput = str | os.PathLike[str] | Protocol


def _validate_protocol_input(protocol_input: ProtocolInput) -> Protocol | None:
    if isinstance(protocol_input, Protocol):
        return protocol_input
    if isinstance(protocol_input, (str, os.PathLike)):
        return None
    raise TypeError(
        "protocol must be a YAML path or protocol_engine.Protocol, "
        f"got {type(protocol_input).__name__}."
    )


def setup_protocol(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_path: ProtocolInput,
    gantry: Any | None = None,
    mock_mode: bool = False,
    data_store: Any | None = None,
    campaign_id: int | None = None,
) -> Tuple[Protocol, ProtocolContext]:
    """Load all configs, validate bounds, and return a ready-to-run protocol.

    Steps:
        1. Load gantry config (working volume and instruments)
        2. Load deck (labware positions)
        3. Build instrumented gantry (mounted instruments with offsets)
        4. Load protocol (command steps)
        5. Validate protocol motion targets within gantry bounds
        6. Validate protocol semantics
        7. Return (Protocol, ProtocolContext)

    Args:
        gantry_path: Path to gantry machine YAML config.
        deck_path: Path to deck YAML config.
        protocol_path: Path to protocol YAML config or a prebuilt Protocol.
        gantry: Optional Gantry instance. If None, an offline Gantry is used
            for validation.
        mock_mode: If True, instantiate real driver classes in offline mode.
        data_store: Optional persistence store attached to the runtime context.
        campaign_id: Optional campaign ID used with ``data_store``.

    Returns:
        Tuple of (Protocol, ProtocolContext) ready for ``protocol.execute(context)``.

    Raises:
        GantryLoaderError: If gantry YAML is invalid or missing.
        DeckLoaderError: If deck YAML is invalid or missing.
        GantryLoaderError: If embedded instruments are invalid or missing.
        ProtocolLoaderError: If protocol YAML is invalid or missing.
        TypeError: If protocol_path is neither a path nor a Protocol.
        SetupValidationError: If any positions violate gantry bounds.
    """
    protocol = _validate_protocol_input(protocol_path)

    gantry_config: GantryConfig = load_gantry_from_yaml_safe(gantry_path)
    validate_deck_origin_minima(gantry_config)
    deck: Deck = load_deck_from_yaml_safe(
        deck_path,
        factory_z_travel_mm=gantry_config.factory_z_travel_mm,
    )

    if gantry is None:
        gantry = Gantry(offline=True)
    try:
        instrumented_gantry: InstrumentedGantry = load_instrumented_gantry_from_config(
            gantry_config, gantry, mock_mode=mock_mode,
        )
    except Exception as exc:
        raise GantryLoaderError(
            f"Machine config error in `{gantry_path}`: {exc}\n"
            "How to fix: Add valid mounted instruments under the "
            "gantry YAML top-level 'instruments' key."
        ) from exc

    if hasattr(gantry, "set_expected_grbl_settings"):
        gantry.set_expected_grbl_settings(
            instrumented_gantry.expected_grbl_settings,
            source=str(gantry_path),
        )

    if protocol is None:
        protocol = load_protocol_from_yaml_safe(protocol_path)

    violations = validate_protocol_motion_bounds(
        gantry_config, protocol, deck, instrumented_gantry,
    )
    if violations:
        raise SetupValidationError(violations)

    semantic_violations = validate_protocol_semantics(
        protocol, instrumented_gantry, deck, gantry_config,
    )
    if semantic_violations:
        raise ProtocolSemanticValidationError(semantic_violations)

    context = ProtocolContext(
        gantry=instrumented_gantry,
        deck=deck,
        positions=protocol.positions,
        gantry_config=gantry_config,
        data_store=data_store,
        campaign_id=campaign_id,
    )
    return protocol, context


def run_on_hardware(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_path: ProtocolInput,
    gantry: Any | None = None,
    mock_mode: bool = False,
    data_store: Any | None = None,
    campaign_id: int | None = None,
    campaign_description: str | None = None,
    protocol_config: str | None = None,
) -> List[Any]:
    """Load configs, validate, and run the protocol as a full hardware session.

    This is the single orchestration path shared by the YAML CLI
    (``setup/run_protocol.py``) and ``Protocol.run()``. Measurement-producing
    commands are persisted by default: when no ``data_store``/``campaign_id`` is
    supplied, this function creates a default ``DataStore`` campaign for the
    run and attaches it to the runtime context. The lifecycle is:

        1. construct a ``Gantry`` from the gantry YAML (when ``gantry`` is None)
        2. create a protocol-run campaign if one was not supplied
        3. ``setup_protocol`` — load/validate configs, build the context
        4. ``gantry.connect()``
        5. ``gantry.prepare_for_protocol_run()`` — clear any startup alarm
        6. ``connect_instruments()``
        7. ``gantry.is_healthy()`` health check (abort if unhealthy)
        8. ``protocol.execute(context)`` — run the steps
        9. disconnect instruments and gantry in ``finally``, even on error

    Args:
        gantry_path: Path to gantry machine YAML config.
        deck_path: Path to deck YAML config.
        protocol_path: Path to protocol YAML config or a prebuilt Protocol.
        gantry: Optional Gantry instance. If None, one is constructed from
            ``gantry_path``. Tests pass an offline Gantry to stay off hardware.
        mock_mode: If True, instantiate real driver classes in offline mode.
        data_store: Optional persistence store attached to the runtime context.
        campaign_id: Optional campaign ID used with ``data_store``. If omitted,
            a campaign is created automatically.
        campaign_description: Optional campaign description for auto-created
            campaigns.
        protocol_config: Optional identifier recorded for in-memory protocol
            objects; YAML path inputs use their own path by default.

    Returns:
        List of step results from protocol execution.

    Raises:
        GantryHealthCheckError: If the gantry health check fails.
    """
    if gantry is None:
        with open(gantry_path) as f:
            raw_config = yaml.safe_load(f)
        gantry = Gantry(config=raw_config)

    owns_data_store = False
    if data_store is None:
        from data import DataStore

        data_store = DataStore()
        owns_data_store = True

    context = None
    try:
        protocol, context = setup_protocol(
            gantry_path, deck_path, protocol_path,
            gantry=gantry, mock_mode=mock_mode,
            data_store=data_store, campaign_id=campaign_id,
        )
        if campaign_id is None:
            from data import register_deck_labware

            protocol_file = _protocol_config_label(protocol_path, protocol_config)
            campaign_id = data_store.create_campaign(
                description=campaign_description or (
                    f"Protocol run: gantry={gantry_path}, deck={deck_path}, "
                    f"protocol={protocol_file}"
                ),
                deck_config=str(deck_path),
                gantry_config=str(gantry_path),
                protocol_config=protocol_file,
            )
            register_deck_labware(data_store, campaign_id, context.deck)
            context.data_store = data_store
            context.campaign_id = campaign_id
        gantry.connect()
        gantry.prepare_for_protocol_run()
        context.gantry.connect_instruments()
        if not gantry.is_healthy():
            raise GantryHealthCheckError(
                "Gantry health check failed before protocol execution; aborting."
            )
        return protocol.execute(context)
    finally:
        if context is not None:
            try:
                context.gantry.disconnect_instruments()
            except Exception as exc:
                logger.error("disconnect_instruments failed: %s", exc, exc_info=True)
            gantry.disconnect()
        if owns_data_store:
            data_store.close()


def _protocol_config_label(
    protocol_input: ProtocolInput,
    explicit: str | None,
) -> str:
    if explicit is not None:
        return explicit
    if isinstance(protocol_input, (str, os.PathLike)):
        return str(protocol_input)
    source_path = getattr(protocol_input, "source_path", None)
    if source_path is not None:
        return str(source_path)
    return "<in-memory protocol>"
