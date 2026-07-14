"""Tests for Protocol, ProtocolStep, and ProtocolContext runtime classes."""

import logging
from unittest.mock import MagicMock

import pytest

import cubos.protocol_engine.setup as protocol_setup
from cubos.protocol_engine.protocol import Protocol, ProtocolSetup
from cubos.protocol_engine.runtime import ProtocolContext, ProtocolStep


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
        protocol.execute(ctx)

        assert call_order == ["a", "b"]

    def test_run_passes_context_to_handlers(self):
        handler = MagicMock(return_value=None)
        steps = [ProtocolStep(index=0, command_name="cmd", handler=handler, args={})]
        protocol = Protocol(steps=steps)
        ctx = _mock_context()
        protocol.execute(ctx)

        handler.assert_called_once_with(ctx)

    def test_run_returns_results_list(self):
        handler_a = MagicMock(return_value="result_a")
        handler_b = MagicMock(return_value="result_b")

        steps = [
            ProtocolStep(index=0, command_name="a", handler=handler_a, args={}),
            ProtocolStep(index=1, command_name="b", handler=handler_b, args={}),
        ]
        protocol = Protocol(steps=steps)
        results = protocol.execute(_mock_context())

        assert results == ["result_a", "result_b"]

    def test_empty_protocol_run_succeeds(self):
        protocol = Protocol(steps=[])
        results = protocol.execute(_mock_context())
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


# ─── Protocol.validate() / Protocol.run() ────────────────────────────────────


class TestProtocolValidate:

    def test_validate_without_setup_raises(self):
        protocol = Protocol(steps=[])
        with pytest.raises(ValueError, match="no setup metadata"):
            protocol.validate()

    def test_validate_with_setup_runs_offline_setup_path(self, monkeypatch):
        calls = {}

        def fake_setup_protocol(gantry_path, deck_path, protocol, **kwargs):
            calls["gantry_path"] = gantry_path
            calls["deck_path"] = deck_path
            calls["protocol"] = protocol
            calls["kwargs"] = kwargs
            return (protocol, MagicMock())

        monkeypatch.setattr(protocol_setup, "setup_protocol", fake_setup_protocol)

        protocol = Protocol(
            steps=[],
            setup=ProtocolSetup(gantry_path="g.yaml", deck_path="d.yaml"),
        )
        protocol.validate()

        assert calls["gantry_path"] == "g.yaml"
        assert calls["deck_path"] == "d.yaml"
        assert calls["protocol"] is protocol
        # Offline: validation must request mock_mode and never touch hardware.
        assert calls["kwargs"].get("mock_mode") is True


class TestProtocolRun:

    def test_run_without_setup_raises(self):
        protocol = Protocol(steps=[])
        with pytest.raises(ValueError, match="setup metadata"):
            protocol.run()

    def test_run_with_setup_delegates_to_run_on_hardware(self, monkeypatch):
        calls = {}

        def fake_run_on_hardware(gantry_path, deck_path, protocol, **kwargs):
            calls["args"] = (gantry_path, deck_path, protocol)
            calls["kwargs"] = kwargs
            return ["ok"]

        monkeypatch.setattr(protocol_setup, "run_on_hardware", fake_run_on_hardware)

        protocol = Protocol(
            steps=[],
            setup=ProtocolSetup(gantry_path="g.yaml", deck_path="d.yaml"),
        )
        results = protocol.run()

        assert results == ["ok"]
        assert calls["args"] == ("g.yaml", "d.yaml", protocol)
        assert calls["kwargs"] == {
            "data_store": None,
            "campaign_description": None,
            "protocol_config": None,
        }

    def test_run_without_campaign_uses_default_persistence(self, monkeypatch):
        passed = {}

        def fake_run_on_hardware(gantry_path, deck_path, protocol, **kwargs):
            passed.update(kwargs)
            return []

        monkeypatch.setattr(protocol_setup, "run_on_hardware", fake_run_on_hardware)

        protocol = Protocol(
            steps=[],
            setup=ProtocolSetup(gantry_path="g.yaml", deck_path="d.yaml"),
        )
        protocol.run()

        assert passed == {
            "data_store": None,
            "campaign_description": None,
            "protocol_config": None,
        }

    def test_run_accepts_data_store_without_campaign(self, monkeypatch):
        passed = {}

        def fake_run_on_hardware(gantry_path, deck_path, protocol, **kwargs):
            passed.update(kwargs)
            return []

        monkeypatch.setattr(protocol_setup, "run_on_hardware", fake_run_on_hardware)

        store = object()
        protocol = Protocol(
            steps=[],
            setup=ProtocolSetup(gantry_path="g.yaml", deck_path="d.yaml"),
        )
        protocol.run(data_store=store)

        assert passed["data_store"] is store
        assert passed["campaign_description"] is None

    def test_run_with_campaign_passes_description_to_hardware_runner(self, monkeypatch):
        passed = {}

        def fake_run_on_hardware(gantry_path, deck_path, protocol, **kwargs):
            passed.update(kwargs)
            return ["ok"]

        store = object()
        monkeypatch.setattr(protocol_setup, "run_on_hardware", fake_run_on_hardware)

        protocol = Protocol(
            steps=[],
            setup=ProtocolSetup(gantry_path="g.yaml", deck_path="d.yaml"),
        )
        results = protocol.run(campaign="My run", data_store=store)

        assert results == ["ok"]
        assert passed["data_store"] is store
        assert passed["campaign_description"] == "My run"
