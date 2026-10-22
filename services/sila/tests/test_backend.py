import asyncio
import json

import httpx
import pytest

from cubos_sila.backend import CubOSBackend
from cubos_sila.config import ProtocolBundle, ProtocolPreset, Settings
from cubos_sila.errors import BackendError


def settings(**kwargs):
    return Settings(
        "455c09ee-3662-4103-befc-46b7cc14b35d",
        presets=(ProtocolPreset("demo", ProtocolBundle("gantry: {}", "deck: {}", "steps: []")),),
        **kwargs,
    )


def backend(handler, **kwargs):
    return CubOSBackend(settings(**kwargs), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def accepted(request):
    submitted = json.loads(request.content)
    return {key: submitted[key] for key in ("run_id", "mock_mode", "metadata")} | {"state": "queued"}


async def test_submit_uses_complete_mock_bundle_auth_and_provenance():
    def handle(request):
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["run_id"] == "chosen-run"
        assert payload["mock_mode"] is True
        assert payload["gantry_config"] == "gantry: {}"
        assert payload["deck_config"] == "deck: {}"
        assert payload["protocol_yaml"] == "steps: []"
        assert not any(key.endswith("_file") for key in payload)
        metadata = payload["metadata"]["cubos_sila"]
        assert metadata["preset"] == "demo"
        assert metadata["execution_id"] == "sila-execution"
        assert len(metadata["bundle_sha256"]) == 64
        return httpx.Response(202, json=accepted(request))
    adapter = backend(handle, api_token="secret")
    record = await adapter.execute_protocol("demo", "chosen-run", execution_id="sila-execution")
    assert record["run_id"] == "chosen-run"
    assert (await adapter.list_protocols())[0]["mode"] == "mock"


@pytest.mark.parametrize("status", [409, 503, "timeout", "invalid_json"])
async def test_uncertain_submission_recovers_same_id_once(status):
    calls = []
    record = None
    def handle(request):
        nonlocal record
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            record = accepted(request)
            if status == "timeout":
                raise httpx.ReadTimeout("the request may have completed", request=request)
            if status == "invalid_json":
                return httpx.Response(202, text="broken")
            return httpx.Response(status, json={"detail": "server busy"})
        return httpx.Response(200, json=record)
    result = await backend(handle).execute_protocol("demo", "chosen-run")
    assert result["run_id"] == "chosen-run"
    assert calls == [("POST", "/api/v1/runs"), ("GET", "/api/v1/runs/chosen-run")]


@pytest.mark.parametrize("change", ["preset", "bundle_sha256", "mock_mode", "run_id", "metadata"])
async def test_existing_mismatched_run_is_never_accepted(change):
    record = None
    def handle(request):
        nonlocal record
        if request.method == "POST":
            record = accepted(request)
            if change in {"preset", "bundle_sha256"}:
                record["metadata"]["cubos_sila"][change] = "other"
            elif change == "mock_mode":
                record[change] = False
            elif change == "metadata":
                record[change] = {}
            else:
                record[change] = "other-run"
            return httpx.Response(409, json={"detail": "already exists"})
        return httpx.Response(200, json=record)
    with pytest.raises(BackendError) as error:
        await backend(handle).execute_protocol("demo", "chosen-run")
    assert error.value.code == "conflict"


@pytest.mark.parametrize("post_status,expected", [(409, "busy"), (503, "unavailable")])
async def test_uncertain_missing_run_preserves_error_and_does_not_replay(post_status, expected):
    calls = []
    def handle(request):
        calls.append(request.method)
        return httpx.Response(post_status if request.method == "POST" else 404, json={"detail": "failure"})
    with pytest.raises(BackendError) as error:
        await backend(handle).execute_protocol("demo", "run")
    assert error.value.code == expected
    assert calls == ["POST", "GET"]


@pytest.mark.parametrize("status,expected", [(400, "invalid_protocol"), (422, "invalid_protocol"), (401, "auth"), (403, "auth")])
async def test_submission_validation_and_auth_failures_not_retried(status, expected):
    calls = []
    def handle(request):
        calls.append(request.method)
        return httpx.Response(status, json={"detail": "rejected secret"})
    with pytest.raises(BackendError) as error:
        await backend(handle, api_token="secret").execute_protocol("demo", "run")
    assert error.value.code == expected
    assert "secret" not in str(error.value)
    assert error.value.status_code == status
    assert calls == ["POST"]


async def test_invalid_arguments_fail_without_network():
    def handle(request):
        pytest.fail("invalid input must not call backend")
    adapter = backend(handle)
    for run_id in ("../escape", "", "x" * 129, "a/b"):
        with pytest.raises(BackendError, match="run_id"):
            await adapter.get_run(run_id)
    with pytest.raises(BackendError, match="unknown configured"):
        await adapter.execute_protocol("unknown", "run")
    with pytest.raises(BackendError, match="nonnegative"):
        await adapter.get_events("run", after=-1)
    for name in ("../secret", "..", "a/b", "a\\b", ""):
        with pytest.raises(BackendError, match="artifact_id"):
            await adapter.get_artifact("run", name)


async def test_routes_cursors_plan_cancel_and_artifacts():
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/events"):
            assert request.url.params["after"] == "12"
            return httpx.Response(200, json={"events": [{"sequence": 13}]})
        if path.endswith("/plan"):
            return httpx.Response(200, json={"steps": [{"index": 0}]})
        if path.endswith("/artifacts"):
            return httpx.Response(200, json={"artifacts": ["result.json"]})
        if path.endswith("/result.json"):
            return httpx.Response(200, content=b"result-data")
        return httpx.Response(202, json={"run_id": "run", "state": "cancel_requested", "mock_mode": True})
    adapter = backend(handle)
    assert (await adapter.get_events("run", after=12))[0]["sequence"] == 13
    assert (await adapter.get_plan("run"))[0]["index"] == 0
    assert await adapter.get_artifacts("run") == ["result.json"]
    assert await adapter.get_artifact("run", "result.json") == b"result-data"
    assert (await adapter.cancel_run("run"))["state"] == "cancel_requested"
    assert calls[-1] == ("POST", "/api/v1/runs/run/cancel")


@pytest.mark.parametrize("operation,code", [("run", "unknown_run"), ("artifact", "unknown_artifact")])
async def test_not_found_errors(operation, code):
    adapter = backend(lambda request: httpx.Response(404, json={"detail": "not found"}))
    with pytest.raises(BackendError) as error:
        if operation == "run":
            await adapter.get_run("run")
        else:
            await adapter.get_artifact("run", "result.json")
    assert error.value.code == code


class Chunked(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"1234"
        yield b"5678"


@pytest.mark.parametrize("declared", [True, False])
async def test_artifact_limit_before_and_during_stream(declared):
    def handle(request):
        if declared:
            return httpx.Response(200, content=b"12345678")
        return httpx.Response(200, stream=Chunked())
    with pytest.raises(BackendError) as error:
        await backend(handle, max_artifact_bytes=5).get_artifact("run", "result.json")
    assert error.value.code == "artifact_too_large"


@pytest.mark.parametrize("response", [b"123456789", b"[]", b"broken"])
async def test_bounded_invalid_json_response(response):
    adapter = backend(lambda request: httpx.Response(200, content=response), max_response_bytes=8)
    with pytest.raises(BackendError) as error:
        await adapter.get_run("run")
    assert error.value.code == "unavailable"


async def test_status_only_reports_observed_hardware_connection():
    def handle(request):
        if request.url.path.endswith("health"):
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path.endswith("position"):
            return httpx.Response(200, json={"connected": False, "status": "Unknown"})
        return httpx.Response(200, json={"instruments": {"uvvis": ["thorlabs"]}})
    status = await backend(handle).status()
    assert status["api_available"] is True
    assert status["hardware_connected"] is False
    assert status["execution_state"] == "unknown"
    assert status["active_run_id"] is None


async def test_unavailable_status_and_authentication_are_distinct():
    adapter = backend(lambda request: httpx.Response(503, json={"detail": "offline"}))
    status = await adapter.status()
    assert status["api_available"] is False
    assert status["hardware_connected"] is None
    adapter = backend(lambda request: httpx.Response(401, json={"detail": "bad token"}))
    with pytest.raises(BackendError) as error:
        await adapter.status()
    assert error.value.code == "auth"


async def test_total_request_deadline_and_event_loop_remain_responsive():
    async def handle(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={})
    adapter = backend(handle, request_timeout_s=0.01)
    with pytest.raises(BackendError) as error:
        await adapter.get_run("run")
    assert error.value.code == "unavailable"


async def test_redirects_are_not_followed_and_injected_client_is_not_closed():
    adapter = backend(lambda request: httpx.Response(307, headers={"location": "http://other.example"}))
    with pytest.raises(BackendError):
        await adapter.get_run("run")
    await adapter.aclose()
    assert not adapter._client.is_closed
    await adapter._client.aclose()


async def test_owned_client_is_closed():
    adapter = CubOSBackend(settings())
    await adapter.aclose()
    assert adapter._client.is_closed


@pytest.mark.parametrize("mock_mode", [False, None])
async def test_mock_only_service_refuses_hardware_cancellation(mock_mode):
    calls = []
    def handle(request):
        calls.append(request.method)
        return httpx.Response(200, json={"run_id": "run", "mock_mode": mock_mode})
    with pytest.raises(BackendError, match="explicit server authorization"):
        await backend(handle).cancel_run("run")
    assert calls == ["GET"]


async def test_authorized_service_can_request_hardware_cancellation():
    calls = []
    def handle(request):
        calls.append(request.method)
        return httpx.Response(200, json={"run_id": "run", "mock_mode": False, "state": "cancel_requested"})
    assert (await backend(handle, allow_hardware=True).cancel_run("run"))["state"] == "cancel_requested"
    assert calls == ["GET", "POST"]


async def test_existing_run_with_mismatched_stored_input_digests_is_rejected():
    record = None
    def handle(request):
        nonlocal record
        if request.method == "POST":
            record = accepted(request) | {"digests": {"gantry_sha256": "different"}}
            return httpx.Response(409, json={"detail": "already exists"})
        return httpx.Response(200, json=record)
    with pytest.raises(BackendError, match="stored run inputs"):
        await backend(handle).execute_protocol("demo", "run")
