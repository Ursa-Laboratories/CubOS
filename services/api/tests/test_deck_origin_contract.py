"""Unsupported gantry coordinate frames never reach the connected runtime."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cubos.gantry.session import GantryPositionSnapshot
from cubos_api.app import create_app
from cubos_api.config import get_settings
from cubos_api.routers import gantry as gantry_router
from cubos_api.routers import instruments as instruments_router
from cubos_api.services.yaml_io import read_yaml, write_yaml
from tests.api_client import api_request


@pytest.fixture
def profile(monkeypatch, tmp_path):
    directory = tmp_path / "configs"
    monkeypatch.setattr(get_settings(), "config_dir", directory)
    monkeypatch.setattr(gantry_router, "_session", None)
    config = {
        "gantry_type": "cub_xl",
        "serial_port": "/dev/offline",
        "cnc": {"factory_z_travel_mm": 110},
        "working_volume": {
            "x_min": 0, "x_max": 300,
            "y_min": 0, "y_max": 200,
            "z_min": 0, "z_max": 80,
        },
        "instruments": {},
    }
    path = directory / "gantry" / "profile.yaml"
    write_yaml(path, config)
    return create_app(), path, config


@pytest.mark.parametrize("policy", ["home_origin", "invalid", None, ["deck_origin"]])
def test_get_and_put_reject_unsupported_frame_without_writing_or_refreshing(profile, monkeypatch, policy):
    app, path, config = profile
    invalid = {**config, "origin_policy": policy}
    write_yaml(path, invalid)
    original = path.read_bytes()
    refresh = Mock()
    monkeypatch.setattr(gantry_router, "_session", SimpleNamespace(refresh_connected_config=refresh))

    for method, body in (("GET", None), ("PUT", invalid)):
        response = api_request(app, method, "/api/v1/gantry/profile.yaml", json=body)
        assert response.status_code == 400
        assert "origin_policy" in response.json()["detail"]
    assert path.read_bytes() == original
    refresh.assert_not_called()


@pytest.mark.parametrize("filename", ["profile.yaml", None])
@pytest.mark.parametrize("contents", ["home_origin", "malformed_yaml"])
def test_connect_rejects_legacy_or_malformed_profile_before_instrument_reset(profile, monkeypatch, filename, contents):
    app, path, config = profile
    if contents == "malformed_yaml":
        path.write_text("origin_policy: [\n", encoding="utf-8")
    else:
        write_yaml(path, {**config, "origin_policy": contents})
    original = path.read_bytes()
    connect = Mock(side_effect=AssertionError("Invalid config must not reach controller connection"))
    reset = Mock(side_effect=AssertionError("Invalid config must not reset instruments"))
    monkeypatch.setattr(gantry_router, "_session", SimpleNamespace(connected=False, connect=connect))
    monkeypatch.setattr(instruments_router, "reset_manual_instruments", reset)

    response = api_request(app, "POST", "/api/v1/gantry/connect", json={"filename": filename})

    assert response.status_code == 400
    assert "Invalid gantry config" in response.json()["detail"]
    assert path.read_bytes() == original
    connect.assert_not_called()
    reset.assert_not_called()


@pytest.mark.parametrize("policy", [None, "deck_origin"])
def test_default_and_explicit_deck_origin_can_load_save_and_connect(profile, monkeypatch, policy):
    app, path, config = profile
    if policy is not None:
        config["origin_policy"] = policy
    response = api_request(app, "PUT", "/api/v1/gantry/profile.yaml", json=config)
    assert response.status_code == 200
    assert response.json()["config"]["origin_policy"] == "deck_origin"
    assert read_yaml(path)["origin_policy"] == "deck_origin"
    assert api_request(app, "GET", "/api/v1/gantry/profile.yaml").status_code == 200
    connect = Mock(return_value=GantryPositionSnapshot(connected=True, status="Idle"))
    reset = Mock()
    monkeypatch.setattr(gantry_router, "_session", SimpleNamespace(connected=False, connect=connect, calibration_active=False))
    monkeypatch.setattr(instruments_router, "reset_manual_instruments", reset)

    response = api_request(app, "POST", "/api/v1/gantry/connect", json={"filename": "profile.yaml"})

    assert response.status_code == 200
    connect.assert_called_once_with(path, filename="profile.yaml")
    reset.assert_called_once_with()


def test_raw_legacy_draft_is_editable_but_cannot_refresh_or_load(profile, monkeypatch):
    app, path, config = profile
    draft = deepcopy(config)
    draft["origin_policy"] = "home_origin"
    write_yaml(path, draft)
    content = path.read_text(encoding="utf-8")
    refresh = Mock()
    monkeypatch.setattr(gantry_router, "_session", SimpleNamespace(refresh_connected_config=refresh))

    response = api_request(app, "PUT", "/api/v1/raw/profile.yaml", json={"content": content})

    assert response.status_code == 200
    assert api_request(app, "GET", "/api/v1/gantry/profile.yaml").status_code == 400
    refresh.assert_not_called()
    corrected = content.replace("home_origin", "deck_origin")
    assert api_request(app, "PUT", "/api/v1/raw/profile.yaml", json={"content": corrected}).status_code == 200
    refresh.assert_called_once()
