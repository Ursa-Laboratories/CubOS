"""Tests for app lifespan cleanup behavior."""

from __future__ import annotations

import asyncio

from zoo import app as zoo_app
from zoo.app import create_app
from zoo.routers import gantry as gantry_router


class RecordingSession:
    connected = True

    def __init__(self):
        self.disconnect_called = False

    def disconnect(self):
        self.disconnect_called = True
        self.connected = False


def _run_lifespan_once() -> None:
    async def run() -> None:
        async with zoo_app.lifespan(create_app()):
            pass

    asyncio.run(run())


def test_lifespan_disconnects_connected_gantry_session(monkeypatch):
    session = RecordingSession()
    monkeypatch.setattr(gantry_router, "_session", session)

    _run_lifespan_once()

    assert session.disconnect_called is True
    assert gantry_router.current_session() is None


def test_lifespan_resets_session_when_disconnect_raises(monkeypatch):
    class FailingSession(RecordingSession):
        def disconnect(self):
            self.disconnect_called = True
            raise RuntimeError("serial died")

    session = FailingSession()
    monkeypatch.setattr(gantry_router, "_session", session)

    _run_lifespan_once()

    assert session.disconnect_called is True
    assert gantry_router.current_session() is None
