"""Tests for the hardware-safe CubOS discovery API."""

from instruments.registry import get_supported_types, get_supported_vendors
from protocol_engine.registry import CommandRegistry

from tests.api_client import api_request
from zoo.app import create_app
from zoo.routers import gantry as gantry_router


def test_health_is_hardware_safe():
    gantry_router.reset_session()
    response = api_request(create_app(), "GET", "/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cubos-server",
        "api_version": "v1",
    }
    assert gantry_router.current_session() is None


def test_version_reports_release_identity(monkeypatch):
    from zoo.routers import system

    versions = {"zoo": "1.2.3", "cubos": "4.5.6"}
    monkeypatch.setattr(system, "_distribution_version", versions.__getitem__)
    monkeypatch.setenv("CUB_BUILD_VERSION", "2026.07.13")
    monkeypatch.setenv("CUB_IMAGE_DIGEST", "sha256:abc123")
    response = api_request(create_app(), "GET", "/api/v1/version")
    assert response.status_code == 200
    assert response.json() == {
        "service": "cubos-server",
        "api_version": "v1",
        "zoo_version": "1.2.3",
        "cubos_version": "4.5.6",
        "build_version": "2026.07.13",
        "image_digest": "sha256:abc123",
    }


def test_capabilities_reflect_cubos_registries():
    response = api_request(create_app(), "GET", "/api/v1/capabilities")
    assert response.status_code == 200
    assert response.json() == {
        "api_version": "v1",
        "commands": CommandRegistry.instance().command_names,
        "instruments": {
            instrument_type: get_supported_vendors(instrument_type)
            for instrument_type in get_supported_types()
        },
    }
