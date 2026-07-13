"""Focused tests for raw YAML editor endpoints."""

from pathlib import Path

from tests.api_client import api_request
from zoo.app import create_app
from zoo.config import get_settings


def test_get_raw_missing_file_returns_404(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(get_settings(), "config_dir", tmp_path)

    response = api_request(create_app(), "GET", "/api/raw/missing.yaml")

    assert response.status_code == 404
    assert response.json()["detail"] == "Config not found: missing.yaml"


def test_get_raw_slash_traversal_is_rejected_by_route(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(get_settings(), "config_dir", tmp_path)

    response = api_request(create_app(), "GET", "/api/raw/..%2Fescape.yaml")

    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_put_raw_classifies_new_protocol_file_into_subdirectory(
    monkeypatch,
    tmp_path: Path,
):
    protocol_dir = tmp_path / "protocol"
    protocol_dir.mkdir()
    monkeypatch.setattr(get_settings(), "config_dir", tmp_path)

    response = api_request(
        create_app(),
        "PUT",
        "/api/raw/new_protocol.yaml",
        json={
            "content": "protocol:\n"
            "  - move:\n"
            "      instrument: pipette\n"
            "      position: plate.A1\n"
        },
    )

    assert response.status_code == 200
    assert (protocol_dir / "new_protocol.yaml").is_file()
    assert not (tmp_path / "new_protocol.yaml").exists()


def test_put_raw_allows_non_mapping_yaml_without_gantry_refresh(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(get_settings(), "config_dir", tmp_path)

    response = api_request(
        create_app(),
        "PUT",
        "/api/raw/list.yaml",
        json={"content": "- one\n- two\n"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "- one\n- two\n"
