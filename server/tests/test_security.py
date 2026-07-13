"""Backend security tests: Origin/Host middleware + path-traversal guards.

Covers the fixes in progress/2026-07-05-audit/04-backend-security.md:
  1. Origin/Host checking middleware (CSRF + DNS-rebinding guard).
  2. safe_filename() applied to {filename} path params (raw.py).
  3. safe_filename() applied to JSON body file-name fields (gantry/protocol).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.api_client import api_request
from zoo.app import create_app
from zoo.config import get_settings


@pytest.fixture(autouse=True)
def restore_config_dir():
    original = get_settings().config_dir
    yield
    get_settings().config_dir = original


def _same_origin() -> str:
    settings = get_settings()
    return f"http://{settings.host}:{settings.port}"


# ── 1. Origin/Host middleware ───────────────────────────────────────────


def test_cross_origin_post_to_gantry_home_is_rejected():
    response = api_request(
        create_app(),
        "POST",
        "/api/gantry/home",
        headers={"origin": "http://evil.example"},
    )
    assert response.status_code == 403


def test_cross_origin_post_via_referer_is_rejected():
    response = api_request(
        create_app(),
        "POST",
        "/api/gantry/home",
        headers={"referer": "http://evil.example/attack.html"},
    )
    assert response.status_code == 403


def test_same_origin_post_passes_through_middleware():
    # Passes the middleware and reaches the route handler (which then 400s
    # because no gantry is connected — proving the middleware let it through
    # rather than blocking it with a 403).
    response = api_request(
        create_app(),
        "POST",
        "/api/gantry/home",
        headers={"origin": _same_origin()},
    )
    assert response.status_code == 400
    assert "not connected" in response.text.lower()


def test_no_origin_or_referer_post_passes_through_middleware():
    # No Origin/Referer header at all (curl, native clients, this test's own
    # client) must not be blocked — only requests that assert a mismatched
    # origin are rejected.
    response = api_request(create_app(), "POST", "/api/gantry/home")
    assert response.status_code == 400
    assert "not connected" in response.text.lower()


def test_evil_host_header_is_rejected():
    response = api_request(
        create_app(),
        "GET",
        "/api/gantry/position",
        headers={"host": "evil.example"},
    )
    assert response.status_code == 400


def test_localhost_and_127_0_0_1_are_equivalent_hosts(monkeypatch):
    monkeypatch.setattr(get_settings(), "host", "127.0.0.1")
    response = api_request(
        create_app(),
        "GET",
        "/api/gantry/position",
        headers={"host": "localhost:8742"},
    )
    assert response.status_code == 200


# ── 2. Path traversal via raw.py {filename} path param ──────────────────


def test_raw_get_rejects_backslash_traversal(tmp_path: Path):
    get_settings().config_dir = tmp_path
    response = api_request(
        create_app(),
        "GET",
        "/api/raw/..%5C..%5Cwindows%5Cevil.bat",
    )
    assert response.status_code == 400


def test_raw_put_rejects_backslash_traversal(tmp_path: Path):
    get_settings().config_dir = tmp_path
    response = api_request(
        create_app(),
        "PUT",
        "/api/raw/..%5C..%5Cwindows%5Cevil.bat",
        json={"content": "malicious"},
    )
    assert response.status_code == 400
    # Nothing should have been written at all — the traversal filename was
    # rejected before any file I/O happened.
    assert list(tmp_path.rglob("*")) == []


def test_raw_get_rejects_dotdot_traversal(tmp_path: Path):
    get_settings().config_dir = tmp_path
    response = api_request(create_app(), "GET", "/api/raw/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code in (400, 404)


def test_raw_put_and_get_roundtrip_still_works_for_plain_filenames(tmp_path: Path):
    get_settings().config_dir = tmp_path
    app = create_app()
    put_response = api_request(
        app, "PUT", "/api/raw/plain.yaml", json={"content": "a: 1\n"}
    )
    assert put_response.status_code == 200
    get_response = api_request(app, "GET", "/api/raw/plain.yaml")
    assert get_response.status_code == 200
    assert get_response.json()["content"] == "a: 1\n"


def test_raw_get_reads_kind_subdirectory(tmp_path: Path):
    get_settings().config_dir = tmp_path
    deck_dir = tmp_path / "deck"
    deck_dir.mkdir()
    (deck_dir / "deck.yaml").write_text("labware: {}\n", encoding="utf-8")

    response = api_request(create_app(), "GET", "/api/raw/deck.yaml")

    assert response.status_code == 200
    assert response.json()["content"] == "labware: {}\n"


def test_raw_put_updates_kind_subdirectory_instead_of_flat_shadow(tmp_path: Path):
    get_settings().config_dir = tmp_path
    protocol_dir = tmp_path / "protocol"
    protocol_dir.mkdir()
    target = protocol_dir / "protocol.yaml"
    target.write_text("protocol: []\n", encoding="utf-8")

    response = api_request(
        create_app(),
        "PUT",
        "/api/raw/protocol.yaml",
        json={"content": "protocol:\n  - move:\n      instrument: pipette\n      position: plate.A1\n"},
    )

    assert response.status_code == 200
    assert target.read_text(encoding="utf-8").startswith("protocol:\n  - move:")
    assert not (tmp_path / "protocol.yaml").exists()


def test_raw_put_rejects_invalid_yaml(tmp_path: Path):
    get_settings().config_dir = tmp_path

    response = api_request(
        create_app(),
        "PUT",
        "/api/raw/bad.yaml",
        json={"content": "protocol: ["},
    )

    assert response.status_code == 400
    assert "Invalid YAML" in response.text
    assert not (tmp_path / "bad.yaml").exists()


# ── 3. Path traversal via JSON body file-name fields ─────────────────────


def test_gantry_connect_rejects_traversal_in_filename_body(tmp_path: Path):
    get_settings().config_dir = tmp_path
    (tmp_path / "gantry").mkdir()
    response = api_request(
        create_app(),
        "POST",
        "/api/gantry/connect",
        json={"filename": "../../../../etc/passwd"},
    )
    assert response.status_code == 400
    assert "root:" not in response.text


def test_protocol_validate_setup_rejects_traversal_in_body_fields(tmp_path: Path):
    get_settings().config_dir = tmp_path
    for subdir in ("gantry", "deck", "protocol"):
        (tmp_path / subdir).mkdir()
    response = api_request(
        create_app(),
        "POST",
        "/api/protocol/validate-setup",
        json={
            "gantry_file": "../../../../etc/passwd",
            "deck_file": "deck.yaml",
            "protocol_file": "protocol.yaml",
        },
    )
    assert response.status_code == 400
    assert "root:" not in response.text


def test_protocol_run_rejects_traversal_in_body_fields(tmp_path: Path):
    get_settings().config_dir = tmp_path
    for subdir in ("gantry", "deck", "protocol"):
        (tmp_path / subdir).mkdir()
    response = api_request(
        create_app(),
        "POST",
        "/api/protocol/run",
        json={
            "gantry_file": "gantry.yaml",
            "deck_file": "deck.yaml",
            "protocol_file": "..\\..\\..\\..\\etc\\passwd",
        },
    )
    assert response.status_code == 400
    assert "root:" not in response.text
