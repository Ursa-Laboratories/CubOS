"""Tests for the move protocol command — unit and end-to-end."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deck.labware.labware import Coordinate3D
from protocol_engine.loader import load_protocol_from_yaml
from protocol_engine.protocol import ProtocolContext


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _mock_context(
    resolve_return: Coordinate3D | None = None,
    positions: dict | None = None,
) -> ProtocolContext:
    """Create a ProtocolContext with mock board and deck."""
    coord = resolve_return or Coordinate3D(x=10.0, y=10.0, z=15.0)

    board = MagicMock()
    deck = MagicMock()
    deck.resolve.return_value = coord

    return ProtocolContext(
        board=board,
        deck=deck,
        positions=positions or {},
        logger=logging.getLogger("test_move"),
    )


# ─── Unit tests: routing by position type ─────────────────────────────────────


class TestMoveCommandRouting:

    def test_deck_target_uses_move_to_labware(self):
        """Deck target strings route through move_to_labware so
        interwell_scan_height is applied (consistent with measure/aspirate)."""
        from protocol_engine.commands.move import move

        coord = Coordinate3D(x=10.0, y=20.0, z=75.0)
        ctx = _mock_context(resolve_return=coord)
        move(ctx, instrument="pipette", position="plate_1.A1")

        ctx.deck.resolve.assert_called_once_with("plate_1.A1")
        ctx.board.move_to_labware.assert_called_once_with("pipette", coord)
        ctx.board.move.assert_not_called()

    def test_literal_list_uses_raw_move(self):
        """[x, y, z] list bypasses move_to_labware — user wants exact coords."""
        from protocol_engine.commands.move import move

        ctx = _mock_context()
        move(ctx, instrument="pipette", position=[100.0, 50.0, 30.0])

        ctx.board.move.assert_called_once_with("pipette", (100.0, 50.0, 30.0))
        ctx.board.move_to_labware.assert_not_called()
        ctx.deck.resolve.assert_not_called()

    def test_literal_tuple_uses_raw_move(self):
        from protocol_engine.commands.move import move

        ctx = _mock_context()
        move(ctx, instrument="pipette", position=(1.0, 2.0, 3.0))

        ctx.board.move.assert_called_once_with("pipette", (1.0, 2.0, 3.0))
        ctx.board.move_to_labware.assert_not_called()

    def test_named_position_uses_raw_move(self):
        """Named position from protocol YAML `positions:` block is literal XYZ."""
        from protocol_engine.commands.move import move

        ctx = _mock_context(positions={"safe": [50.0, 50.0, 70.0]})
        move(ctx, instrument="pipette", position="safe")

        ctx.board.move.assert_called_once_with("pipette", (50.0, 50.0, 70.0))
        ctx.board.move_to_labware.assert_not_called()
        ctx.deck.resolve.assert_not_called()

    def test_named_position_forwards_travel_z(self):
        from protocol_engine.commands.move import move

        ctx = _mock_context(positions={"safe": [50.0, 50.0, 70.0]})
        move(ctx, instrument="pipette", position="safe", travel_z=80.0)

        ctx.board.move.assert_called_once_with(
            "pipette", (50.0, 50.0, 70.0), travel_z=80.0,
        )
        ctx.board.move_to_labware.assert_not_called()
        ctx.deck.resolve.assert_not_called()

    def test_passes_instrument_name_through_deck_path(self):
        from protocol_engine.commands.move import move

        ctx = _mock_context()
        move(ctx, instrument="filmetrics", position="vial_1")

        call_args = ctx.board.move_to_labware.call_args
        assert call_args[0][0] == "filmetrics"

    def test_invalid_deck_target_propagates_error(self):
        """A dotted position (looks like a deck target) that fails to
        resolve propagates the underlying error unwrapped."""
        from protocol_engine.commands.move import move

        ctx = _mock_context()
        ctx.deck.resolve.side_effect = KeyError("No labware 'bad' on deck.")

        with pytest.raises(KeyError, match="bad"):
            move(ctx, instrument="pipette", position="bad.A1")

    def test_bare_string_typo_mentions_both_namespaces(self):
        """A non-dotted string that's neither a named position nor a
        deck labware key gets a clear error listing both namespaces —
        catches typos like 'home_postion' vs 'home_position'."""
        from protocol_engine.commands.move import move
        from protocol_engine.errors import ProtocolExecutionError

        ctx = _mock_context(positions={"home_position": [0, 0, 80]})
        ctx.deck.resolve.side_effect = KeyError("Not found")

        with pytest.raises(ProtocolExecutionError, match="home_postion"):
            move(ctx, instrument="pipette", position="home_postion")

    def test_deck_target_rejects_travel_z_override(self):
        from protocol_engine.commands.move import move
        from protocol_engine.errors import ProtocolExecutionError

        ctx = _mock_context()

        with pytest.raises(ProtocolExecutionError, match="travel_z is only supported"):
            move(ctx, instrument="pipette", position="plate_1.A1", travel_z=80.0)


# ─── End-to-end: YAML → load → run ──────────────────────────────────────────


class TestMoveEndToEnd:

    def test_yaml_deck_targets_route_to_move_to_labware(self):
        yaml_content = """
protocol:
  - move:
      instrument: pipette
      position: plate_1.A1
  - move:
      instrument: pipette
      position: plate_1.C9
"""
        coord_a1 = Coordinate3D(x=10.0, y=10.0, z=15.0)
        coord_c9 = Coordinate3D(x=62.0, y=28.0, z=15.0)
        deck = MagicMock()

        def resolve_side_effect(target: str) -> Coordinate3D:
            if target == "plate_1.A1":
                return coord_a1
            if target == "plate_1.C9":
                return coord_c9
            raise KeyError(f"No labware for '{target}'")

        deck.resolve.side_effect = resolve_side_effect
        board = MagicMock()
        ctx = ProtocolContext(board=board, deck=deck)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            protocol = load_protocol_from_yaml(path)
            assert len(protocol) == 2
            protocol.run(ctx)

            assert deck.resolve.call_count == 2
            assert board.move_to_labware.call_count == 2
            board.move_to_labware.assert_any_call("pipette", coord_a1)
            board.move_to_labware.assert_any_call("pipette", coord_c9)
            board.move.assert_not_called()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_yaml_literal_coords_use_raw_move(self):
        yaml_content = """
protocol:
  - move:
      instrument: pipette
      position: [100.0, 50.0, 30.0]
"""
        ctx = _mock_context()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            protocol = load_protocol_from_yaml(path)
            protocol.run(ctx)

            ctx.board.move.assert_called_once_with("pipette", (100.0, 50.0, 30.0))
            ctx.board.move_to_labware.assert_not_called()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_yaml_named_position_forwards_travel_z(self):
        yaml_content = """
positions:
  safe_z: [0.0, 0.0, 20.0]
protocol:
  - move:
      instrument: pipette
      position: safe_z
      travel_z: 20.0
"""
        ctx = _mock_context(positions={"safe_z": [0.0, 0.0, 20.0]})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            protocol = load_protocol_from_yaml(path)
            protocol.run(ctx)

            ctx.board.move.assert_called_once_with(
                "pipette", (0.0, 0.0, 20.0), travel_z=20.0,
            )
            ctx.board.move_to_labware.assert_not_called()
        finally:
            Path(path).unlink(missing_ok=True)
