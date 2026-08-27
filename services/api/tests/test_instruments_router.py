"""Tests for the manual instrument control endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.api_client import api_request
from cubos_api.app import create_app
from cubos_api.routers import gantry as gantry_router
from cubos_api.routers import instruments as instruments_router


@pytest.fixture(autouse=True)
def _reset_manual_instruments():
    instruments_router.reset_manual_instruments()
    yield
    instruments_router.reset_manual_instruments()


@pytest.fixture
def connected_session(monkeypatch):
    """Fake a connected gantry session carrying an imaging config."""
    config = {
        "instruments": {
            "lights": {
                "type": "lighting",
                "vendor": "pawduino",
                "port": "",
                "offline": True,
            },
            "camera": {
                "type": "camera",
                "vendor": "flir",
                "camera_id": 0,
                "offline": True,
            },
            "pipette": {
                "type": "pipette",
                "vendor": "opentrons",
                "offline": True,
            },
        }
    }
    session = SimpleNamespace(connected=True, connected_gantry_config=config)
    monkeypatch.setattr(
        instruments_router, "_require_session", lambda: session,
    )
    return session


@pytest.fixture
def images_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBOS_IMAGES_DIR", str(tmp_path / "images"))
    return tmp_path / "images"


class TestLighting:
    def test_list_reports_channels_before_any_connect(self, connected_session):
        response = api_request(create_app(), "GET", "/api/v1/instruments/lighting")
        assert response.status_code == 200
        (entry,) = response.json()
        assert entry["instrument"] == "lights"
        assert entry["connected"] is False
        assert entry["channels"]["white"] == [5, 10, 15, 25, 50, 100]
        assert entry["channels"]["contact"] == [5, 10, 20, 30, 50]
        assert entry["active"] == {"white": 0, "contact": 0}

    def test_set_channel_then_all_off(self, connected_session):
        app = create_app()
        response = api_request(
            app, "POST", "/api/v1/instruments/lighting/set",
            json={"instrument": "lights", "channel": "white", "brightness": 25},
        )
        assert response.status_code == 200
        assert response.json()["active"]["white"] == 25

        response = api_request(
            app, "POST", "/api/v1/instruments/lighting/set",
            json={"instrument": "lights", "all_off": True},
        )
        assert response.status_code == 200
        assert response.json()["active"] == {"white": 0, "contact": 0}

    def test_unsupported_level_400(self, connected_session):
        response = api_request(
            create_app(), "POST", "/api/v1/instruments/lighting/set",
            json={"instrument": "lights", "channel": "white", "brightness": 42},
        )
        assert response.status_code == 400
        assert "does not support" in response.json()["detail"]

    def test_unknown_instrument_404(self, connected_session):
        response = api_request(
            create_app(), "POST", "/api/v1/instruments/lighting/set",
            json={"instrument": "nope", "all_off": True},
        )
        assert response.status_code == 404

    def test_wrong_type_400(self, connected_session):
        response = api_request(
            create_app(), "POST", "/api/v1/instruments/lighting/set",
            json={"instrument": "camera", "all_off": True},
        )
        assert response.status_code == 400
        assert "not a lighting instrument" in response.json()["detail"]

    def test_rejected_while_run_active(self, connected_session):
        gantry_router.begin_run()
        try:
            response = api_request(
                create_app(), "POST", "/api/v1/instruments/lighting/set",
                json={"instrument": "lights", "all_off": True},
            )
        finally:
            gantry_router.end_run()
        assert response.status_code == 409

    def test_requires_connected_gantry(self):
        response = api_request(create_app(), "GET", "/api/v1/instruments/lighting")
        assert response.status_code == 400


class TestCamera:
    def test_capture_and_last_image(self, connected_session, images_dir):
        app = create_app()
        response = api_request(
            app, "POST", "/api/v1/instruments/camera/capture",
            json={"instrument": "camera", "label": "focus-check"},
        )
        assert response.status_code == 200
        image_path = response.json()["image_path"]
        assert "manual" in image_path and image_path.endswith(".png")

        listing = api_request(app, "GET", "/api/v1/instruments/camera")
        (entry,) = listing.json()
        assert entry["last_image"] == image_path

        image = api_request(
            app, "GET", "/api/v1/instruments/camera/last-image",
            params={"instrument": "camera"},
        )
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_last_image_404_before_any_capture(self, connected_session):
        response = api_request(
            create_app(), "GET", "/api/v1/instruments/camera/last-image",
            params={"instrument": "camera"},
        )
        assert response.status_code == 404

    def test_capture_rejected_while_run_active(self, connected_session, images_dir):
        gantry_router.begin_run()
        try:
            response = api_request(
                create_app(), "POST", "/api/v1/instruments/camera/capture",
                json={"instrument": "camera"},
            )
        finally:
            gantry_router.end_run()
        assert response.status_code == 409
