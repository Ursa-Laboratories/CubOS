"""Tests for Protocol, ProtocolStep, and ProtocolContext runtime classes."""

import logging
from unittest.mock import MagicMock

import pytest

from protocol_engine.protocol import Protocol, ProtocolContext, ProtocolStep


def _mock_context():
    return ProtocolContext(
        gantry=MagicMock(),
        deck=MagicMock(),
        logger=logging.getLogger("test_protocol"),
    )


# ─── ProtocolStep ────────────────────────────────────────────────────────────


class TestProtocolStep:

    def test_execute_calls_handler_with_context_and_kwargs(self):
        handler = MagicMock(return_value="ok")
        step = ProtocolStep(
            index=0,
            command_name="move",
            handler=handler,
            args={"instrument": "pipette", "position": "plate_1.A1"},
        )
        ctx = _mock_context()
        result = step.execute(ctx)

        handler.assert_called_once_with(ctx, instrument="pipette", position="plate_1.A1")
        assert result == "ok"

    def test_execute_with_empty_args(self):
        handler = MagicMock(return_value=None)
        step = ProtocolStep(index=0, command_name="home", handler=handler, args={})
        ctx = _mock_context()
        step.execute(ctx)

        handler.assert_called_once_with(ctx)


# ─── Protocol ────────────────────────────────────────────────────────────────


class TestProtocol:

    def test_run_executes_all_steps_in_order(self):
        call_order = []
        handler_a = MagicMock(side_effect=lambda ctx, **kw: call_order.append("a"))
        handler_b = MagicMock(side_effect=lambda ctx, **kw: call_order.append("b"))

        steps = [
            ProtocolStep(index=0, command_name="a", handler=handler_a, args={"x": "1"}),
            ProtocolStep(index=1, command_name="b", handler=handler_b, args={"y": "2"}),
        ]
        protocol = Protocol(steps=steps)
        ctx = _mock_context()
        protocol.run(ctx)

        assert call_order == ["a", "b"]

    def test_run_passes_context_to_handlers(self):
        handler = MagicMock(return_value=None)
        steps = [ProtocolStep(index=0, command_name="cmd", handler=handler, args={})]
        protocol = Protocol(steps=steps)
        ctx = _mock_context()
        protocol.run(ctx)

        handler.assert_called_once_with(ctx)

    def test_run_returns_results_list(self):
        handler_a = MagicMock(return_value="result_a")
        handler_b = MagicMock(return_value="result_b")

        steps = [
            ProtocolStep(index=0, command_name="a", handler=handler_a, args={}),
            ProtocolStep(index=1, command_name="b", handler=handler_b, args={}),
        ]
        protocol = Protocol(steps=steps)
        results = protocol.run(_mock_context())

        assert results == ["result_a", "result_b"]

    def test_empty_protocol_run_succeeds(self):
        protocol = Protocol(steps=[])
        results = protocol.run(_mock_context())
        assert results == []

    def test_protocol_len(self):
        steps = [
            ProtocolStep(index=0, command_name="a", handler=MagicMock(), args={}),
            ProtocolStep(index=1, command_name="b", handler=MagicMock(), args={}),
        ]
        assert len(Protocol(steps=steps)) == 2
        assert len(Protocol(steps=[])) == 0

    def test_protocol_repr(self):
        steps = [
            ProtocolStep(index=0, command_name="move", handler=MagicMock(), args={}),
            ProtocolStep(index=1, command_name="aspirate", handler=MagicMock(), args={}),
        ]
        assert repr(Protocol(steps=steps)) == "Protocol([move, aspirate])"

    def test_protocol_steps_property_returns_copy(self):
        steps = [ProtocolStep(index=0, command_name="a", handler=MagicMock(), args={})]
        protocol = Protocol(steps=steps)
        returned = protocol.steps
        returned.append(ProtocolStep(index=1, command_name="b", handler=MagicMock(), args={}))
        assert len(protocol) == 1
