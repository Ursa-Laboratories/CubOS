"""Tests for the hardware-safe CubOS discovery API."""

from cubos.instruments.registry import get_supported_types, get_supported_vendors
from cubos.protocol_engine.registry import CommandRegistry

from tests.api_client import api_request
from cubos_api.app import create_app
from cubos_api.routers import gantry as gantry_router


def test_health_is_hardware_safe(monkeypatch):
    from cubos_api.routers import system

    gantry_router.reset_session()
    versions = {"cubos-api": "1.2.3", "cubos": "4.5.6"}
    monkeypatch.setattr(system, "_distribution_version", versions.__getitem__)
    monkeypatch.setenv("CUBOS_BUILD_VERSION", "2026.07.13")
    response = api_request(create_app(), "GET", "/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cubos-api",
        "api_version": "v1",
        "server_version": "1.2.3",
        "cubos_version": "4.5.6",
        "build_version": "2026.07.13",
        "run_schema_version": "1",
        "checks": {
            "configs": "writable",
            "runs": "writable",
            "data": "writable",
            "run_schema": "compatible",
        },
    }
    assert gantry_router.current_session() is None


def test_health_returns_503_for_unwritable_storage(monkeypatch):
    from cubos_api.routers import system

    def fail(path):
        if path == get_settings().run_dir.expanduser().resolve():
            raise OSError("read only")
        return "writable"

    from cubos_api.config import get_settings

    monkeypatch.setattr(system, "_writable_directory", fail)
    response = api_request(create_app(), "GET", "/api/v1/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["runs"].startswith("unwritable:")


def test_version_reports_release_identity(monkeypatch):
    from cubos_api.routers import system

    versions = {"cubos-api": "1.2.3", "cubos": "4.5.6"}
    monkeypatch.setattr(system, "_distribution_version", versions.__getitem__)
    monkeypatch.setenv("CUBOS_BUILD_VERSION", "2026.07.13")
    monkeypatch.setenv("CUBOS_IMAGE_DIGEST", "sha256:abc123")
    response = api_request(create_app(), "GET", "/api/v1/version")
    assert response.status_code == 200
    assert response.json() == {
        "service": "cubos-api",
        "api_version": "v1",
        "api_service_version": "1.2.3",
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
