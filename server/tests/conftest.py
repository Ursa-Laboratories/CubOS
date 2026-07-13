"""Shared pytest fixtures for the Zoo backend test suite."""

import pytest

from zoo.config import get_settings
from zoo.routers import gantry as gantry_router
from zoo.services.run_manager import reset_run_manager


@pytest.fixture(autouse=True)
def _reset_gantry_run_state():
    """Ensure the protocol-run-in-progress gate never leaks between tests."""
    gantry_router.end_run()
    yield
    gantry_router.end_run()


@pytest.fixture(autouse=True)
def _isolate_versioned_run_store(tmp_path):
    settings = get_settings()
    original = {
        "run_dir": settings.run_dir,
        "api_token": settings.api_token,
        "allowed_commands": list(settings.allowed_commands),
        "allowed_instruments": list(settings.allowed_instruments),
        "expected_gantry_sha256": settings.expected_gantry_sha256,
        "expected_deck_sha256": settings.expected_deck_sha256,
    }
    settings.run_dir = tmp_path / "runs"
    settings.api_token = None
    settings.allowed_commands = []
    settings.allowed_instruments = []
    settings.expected_gantry_sha256 = None
    settings.expected_deck_sha256 = None
    reset_run_manager()
    yield
    reset_run_manager()
    for name, value in original.items():
        setattr(settings, name, value)


@pytest.fixture(autouse=True)
def _allow_testserver_host():
    """Allow the ASGI test client's Host header through the Origin/Host
    middleware (zoo.app._origin_host_middleware).

    httpx's ``ASGITransport`` with ``base_url="http://testserver"`` sends
    ``Host: testserver`` on every request. Production stays strict —
    ``trusted_hosts`` defaults to empty — but tests need this one extra
    hostname allowed so the DNS-rebinding guard doesn't 400 every request.
    """
    settings = get_settings()
    original = list(settings.trusted_hosts)
    settings.trusted_hosts = list(set(original) | {"testserver"})
    yield
    settings.trusted_hosts = original
