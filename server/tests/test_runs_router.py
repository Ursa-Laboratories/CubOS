"""Contract tests for asynchronous versioned CubOS runs."""

from __future__ import annotations

import hashlib
import time
from threading import Event

from tests.api_client import api_request
from zoo.app import create_app
from zoo.config import get_settings


GANTRY_YAML = "name: test-gantry\n"
DECK_YAML = "labware: {}\n"
PROTOCOL_YAML = "protocol:\n  - home: null\n"


def _payload(run_id: str = "run-001") -> dict:
    return {
        "run_id": run_id,
        "gantry_config": GANTRY_YAML,
        "deck_config": DECK_YAML,
        "protocol_yaml": PROTOCOL_YAML,
        "metadata": {"sample": "A1"},
    }


def _wait_for_state(app, run_id: str, *states: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = api_request(app, "GET", f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["state"] in states:
            return body
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {states}")


def test_submit_returns_202_and_persists_artifacts(monkeypatch):
    from zoo.routers import gantry as gantry_router

    monkeypatch.setattr(
        gantry_router,
        "run_protocol_on_session",
        lambda **_kwargs: type(
            "Result",
            (),
            {
                "status": "ok",
                "steps_executed": 1,
                "campaign_id": 7,
                "results": [{"well": "A1", "force": 0.42}],
            },
        )(),
    )
    app = create_app()
    response = api_request(app, "POST", "/api/v1/runs", json=_payload())
    assert response.status_code == 202
    assert response.headers["location"] == "/api/v1/runs/run-001"
    assert response.json()["digests"]["protocol_sha256"] == hashlib.sha256(
        PROTOCOL_YAML.encode()
    ).hexdigest()

    completed = _wait_for_state(app, "run-001", "succeeded")
    assert completed["result"] == {
        "campaign_id": 7,
        "results": [{"force": 0.42, "well": "A1"}],
        "status": "ok",
        "steps_executed": 1,
    }
    artifacts = api_request(app, "GET", "/api/v1/runs/run-001/artifacts").json()
    assert "protocol.yaml" in artifacts["artifacts"]
    assert "result.json" in artifacts["artifacts"]
    protocol = api_request(
        app, "GET", "/api/v1/runs/run-001/artifacts/protocol.yaml"
    )
    assert protocol.status_code == 200
    assert protocol.text == PROTOCOL_YAML


def test_run_events_are_ordered_and_filterable(monkeypatch):
    from zoo.routers import gantry as gantry_router

    monkeypatch.setattr(gantry_router, "run_protocol_on_session", lambda **_kwargs: {"ok": True})
    app = create_app()
    api_request(app, "POST", "/api/v1/runs", json=_payload())
    _wait_for_state(app, "run-001", "succeeded")
    events = api_request(app, "GET", "/api/v1/runs/run-001/events").json()["events"]
    assert [event["state"] for event in events] == ["queued", "running", "succeeded"]
    filtered = api_request(
        app, "GET", "/api/v1/runs/run-001/events?after=1"
    ).json()["events"]
    assert [event["sequence"] for event in filtered] == [2, 3]


def test_second_run_is_rejected_while_first_is_active(monkeypatch):
    from zoo.routers import gantry as gantry_router

    release = Event()
    monkeypatch.setattr(
        gantry_router,
        "run_protocol_on_session",
        lambda **_kwargs: release.wait(timeout=2) or {"ok": True},
    )
    app = create_app()
    first = api_request(app, "POST", "/api/v1/runs", json=_payload("first"))
    assert first.status_code == 202
    _wait_for_state(app, "first", "running")
    second = api_request(app, "POST", "/api/v1/runs", json=_payload("second"))
    assert second.status_code == 409
    assert "busy with run 'first'" in second.text
    release.set()
    _wait_for_state(app, "first", "succeeded")


def test_cancel_uses_existing_session_interrupt(monkeypatch):
    from zoo.routers import gantry as gantry_router

    release = Event()
    interrupted = Event()

    def execute(**_kwargs):
        release.wait(timeout=2)
        return {"ok": True}

    monkeypatch.setattr(gantry_router, "run_protocol_on_session", execute)
    monkeypatch.setattr(gantry_router, "request_feed_hold_interrupt", interrupted.set)
    app = create_app()
    api_request(app, "POST", "/api/v1/runs", json=_payload())
    _wait_for_state(app, "run-001", "running")
    response = api_request(app, "POST", "/api/v1/runs/run-001/cancel")
    assert response.status_code == 202
    assert response.json()["state"] == "cancel_requested"
    assert interrupted.is_set()
    release.set()
    _wait_for_state(app, "run-001", "succeeded")


def test_allow_list_and_config_digest_are_enforced():
    settings = get_settings()
    settings.allowed_commands = ["move"]
    app = create_app()
    denied = api_request(app, "POST", "/api/v1/runs", json=_payload())
    assert denied.status_code == 400
    assert "command 'home' is not allowed" in denied.text

    settings.allowed_commands = ["home"]
    settings.expected_gantry_sha256 = "not-the-real-digest"
    denied = api_request(app, "POST", "/api/v1/runs", json=_payload())
    assert denied.status_code == 400
    assert "digest does not match" in denied.text


def test_native_state_changes_require_token_when_configured(monkeypatch):
    from pydantic import SecretStr
    from zoo.routers import gantry as gantry_router

    get_settings().api_token = SecretStr("device-secret")
    monkeypatch.setattr(gantry_router, "run_protocol_on_session", lambda **_kwargs: {})
    app = create_app()
    denied = api_request(app, "POST", "/api/v1/runs", json=_payload())
    assert denied.status_code == 401
    accepted = api_request(
        app,
        "POST",
        "/api/v1/runs",
        json=_payload(),
        headers={"authorization": "Bearer device-secret"},
    )
    assert accepted.status_code == 202
    _wait_for_state(app, "run-001", "succeeded")


def test_unsafe_or_incomplete_submissions_are_rejected():
    app = create_app()
    unsafe = api_request(app, "POST", "/api/v1/runs", json=_payload("../escape"))
    assert unsafe.status_code == 422
    incomplete = api_request(
        app,
        "POST",
        "/api/v1/runs",
        json={"gantry_config": GANTRY_YAML, "deck_config": DECK_YAML},
    )
    assert incomplete.status_code == 422


def test_missing_run_and_artifact_return_404():
    app = create_app()
    assert api_request(app, "GET", "/api/v1/runs/missing").status_code == 404
    assert (
        api_request(app, "GET", "/api/v1/runs/missing/artifacts/result.json").status_code
        == 404
    )
