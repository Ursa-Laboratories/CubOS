"""Protocol setup: load all configs, validate, and return a ready-to-run protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

from board.board import Board
from board.errors import BoardLoaderError
from board.loader import load_board_from_gantry_config, load_board_from_yaml_safe
from deck.deck import Deck
from deck.loader import load_deck_from_yaml_safe
from gantry.gantry import Gantry
from gantry.gantry_config import GantryConfig
from gantry.loader import load_gantry_from_yaml_safe
from gantry.origin import validate_deck_origin_minima
from protocol_engine.loader import load_protocol_from_yaml_safe
from protocol_engine.protocol import Protocol, ProtocolContext
from validation.bounds import validate_deck_positions, validate_gantry_positions
from validation.errors import ProtocolSemanticValidationError, SetupValidationError
from validation.protocol_semantics import validate_protocol_semantics


def setup_protocol(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_or_board_path: str | Path,
    protocol_path: str | Path | None = None,
    gantry: Any | None = None,
    mock_mode: bool = False,
) -> Tuple[Protocol, ProtocolContext]:
    """Load all configs, validate bounds, and return a ready-to-run protocol.

    Steps:
        1. Load gantry config (working volume, homing strategy, instruments)
        2. Load deck (labware positions)
        3. Build board (instruments with offsets)
        4. Load protocol (command steps)
        5. Validate all deck positions within gantry bounds
        6. Validate all gantry positions within gantry bounds
        7. Return (Protocol, ProtocolContext)

    Args:
        gantry_path: Path to gantry machine YAML config.
        deck_path: Path to deck YAML config.
        protocol_or_board_path: Path to protocol YAML config. For legacy
            callers only, this can be a board YAML when protocol_path is also
            supplied.
        protocol_path: Optional protocol YAML path for the legacy
            gantry/deck/board/protocol call shape.
        gantry: Optional Gantry instance. If None, an offline Gantry is used
            for validation.
        mock_mode: If True, instantiate real driver classes in offline mode.

    Returns:
        Tuple of (Protocol, ProtocolContext) ready for ``protocol.run(context)``.

    Raises:
        GantryLoaderError: If gantry YAML is invalid or missing.
        DeckLoaderError: If deck YAML is invalid or missing.
        BoardLoaderError: If embedded instruments are invalid or missing.
        ProtocolLoaderError: If protocol YAML is invalid or missing.
        SetupValidationError: If any positions violate gantry bounds.
    """
    board_path: str | Path | None = None
    if protocol_path is None:
        protocol_path = protocol_or_board_path
    else:
        board_path = protocol_or_board_path

    gantry_config: GantryConfig = load_gantry_from_yaml_safe(gantry_path)
    validate_deck_origin_minima(gantry_config)
    deck: Deck = load_deck_from_yaml_safe(
        deck_path,
        total_z_range=gantry_config.total_z_range,
    )

    if gantry is None:
        gantry = Gantry(offline=True)
    if board_path is None:
        try:
            board: Board = load_board_from_gantry_config(
                gantry_config, gantry, mock_mode=mock_mode,
            )
        except Exception as exc:
            raise BoardLoaderError(
                f"Machine config error in `{gantry_path}`: {exc}\n"
                "How to fix: Add valid mounted instruments under the "
                "gantry YAML top-level 'instruments' key."
            ) from exc
        settings_source = str(gantry_path)
    else:
        board = load_board_from_yaml_safe(
            board_path, gantry, mock_mode=mock_mode,
        )
        settings_source = str(board_path)

    if hasattr(gantry, "set_expected_grbl_settings"):
        gantry.set_expected_grbl_settings(
            board.expected_grbl_settings,
            source=settings_source,
        )

    protocol: Protocol = load_protocol_from_yaml_safe(protocol_path)

    violations = validate_deck_positions(gantry_config, deck)
    violations.extend(validate_gantry_positions(gantry_config, deck, board))
    if violations:
        raise SetupValidationError(violations)

    semantic_violations = validate_protocol_semantics(
        protocol, board, deck, gantry_config,
    )
    if semantic_violations:
        raise ProtocolSemanticValidationError(semantic_violations)

    context = ProtocolContext(board=board, deck=deck, positions=protocol.positions, gantry=gantry_config)
    return protocol, context


def run_protocol(
    gantry_path: str | Path,
    deck_path: str | Path,
    protocol_or_board_path: str | Path,
    protocol_path: str | Path | None = None,
    gantry: Any | None = None,
    mock_mode: bool = False,
) -> List[Any]:
    """Load configs, validate, and execute the protocol in one call.

    Connects instruments before running and disconnects them afterwards,
    even if the protocol raises an exception.

    Returns:
        List of step results from protocol execution.
    """
    protocol, context = setup_protocol(
        gantry_path, deck_path, protocol_or_board_path, protocol_path,
        gantry=gantry, mock_mode=mock_mode,
    )
    context.board.connect_instruments()
    try:
        return protocol.run(context)
    finally:
        context.board.disconnect_instruments()
