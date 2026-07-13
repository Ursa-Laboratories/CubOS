"""Test settings API config directory contract."""

import json
import tempfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from tests.api_client import api_request
from zoo.app import create_app
from zoo.config import ZooSettings, get_settings


@pytest.fixture(autouse=True)
def restore_config_dir(monkeypatch, tmp_path):
    original = get_settings().config_dir
    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("ZOO_SETTINGS_FILE", str(settings_file))
    monkeypatch.delenv("ZOO_CONFIG_DIR", raising=False)
    yield settings_file
    get_settings().config_dir = original


def test_get_settings_returns_config_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(get_settings(), "config_dir", Path(d))
        app = create_app()

        response = api_request(app, "GET", "/api/settings")

        assert response.status_code == 200
        assert response.json() == {"config_dir": str(Path(d).resolve())}


def test_settings_endpoint_reports_existing_local_directory(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d)
        monkeypatch.setattr(get_settings(), "config_dir", path)
        app = create_app()

        response = api_request(app, "GET", "/api/settings")

        assert response.status_code == 200
        assert response.json()["config_dir"] == str(path.resolve())
        assert path.is_dir()


def test_update_settings_accepts_config_dir():
    with tempfile.TemporaryDirectory() as d:
        app = create_app()

        response = api_request(app, "PUT", "/api/settings", json={"config_dir": d})

        assert response.status_code == 200
        assert response.json() == {"config_dir": str(Path(d).resolve())}
        assert get_settings().config_dir == Path(d).resolve()


def test_update_settings_persists_config_dir(restore_config_dir):
    with tempfile.TemporaryDirectory() as d:
        app = create_app()

        response = api_request(app, "PUT", "/api/settings", json={"config_dir": d})

        assert response.status_code == 200
        assert json.loads(restore_config_dir.read_text(encoding="utf-8")) == {
            "config_dir": str(Path(d).resolve())
        }


def test_zoo_settings_loads_persisted_config_dir(restore_config_dir):
    with tempfile.TemporaryDirectory() as d:
        restore_config_dir.write_text(
            json.dumps({"config_dir": d}),
            encoding="utf-8",
        )

        settings = ZooSettings()

        assert settings.configs_dir == Path(d).resolve()


def test_zoo_config_dir_env_wins_over_persisted_settings(monkeypatch, restore_config_dir, tmp_path):
    persisted = tmp_path / "persisted"
    env_dir = tmp_path / "env"
    persisted.mkdir()
    env_dir.mkdir()
    restore_config_dir.write_text(
        json.dumps({"config_dir": str(persisted)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ZOO_CONFIG_DIR", str(env_dir))

    settings = ZooSettings()

    assert settings.configs_dir == env_dir.resolve()


def test_update_settings_rejects_invalid_path():
    app = create_app()

    response = api_request(app, "PUT", "/api/settings", json={"config_dir": "/does/not/exist"})

    assert response.status_code == 400
    assert "Directory does not exist" in response.text


def test_browse_directory_returns_selected_config_dir(monkeypatch):
    selected = "/tmp/zoo-configs"

    monkeypatch.setattr(
        "zoo.routers.settings.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args=args[0], returncode=0, stdout=f"{selected}\n"),
    )

    app = create_app()
    response = api_request(app, "POST", "/api/settings/browse")

    assert response.status_code == 200
    assert response.json() == {"config_dir": selected}


def test_browse_directory_wraps_picker_failures(monkeypatch):
    monkeypatch.setattr(
        "zoo.routers.settings.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no display")),
    )

    response = api_request(create_app(), "POST", "/api/settings/browse")

    assert response.status_code == 400
    assert "Directory picker failed" in response.text
