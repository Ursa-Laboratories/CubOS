"""Independent SiLA clients exercise the real CubOS mock protocol engine."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET

import httpx
import pytest
import pytest_asyncio
from sila.client import Client, ClientConfig
from sila.framework import CommandExecutionStatus, DefinedExecutionError, ValidationError

from cubos_api.app import create_app
from cubos_api.config import get_settings
from cubos_api.routers import gantry as gantry_router
from cubos_api.services.run_manager import reset_run_manager
from cubos_sila.backend import CubOSBackend
from cubos_sila.config import ProtocolBundle, ProtocolPreset, Settings
from cubos_sila.connector import CubOSConnector


GANTRY_YAML = """\
serial_port: /dev/null
gantry_type: cub_xl
cnc:
  factory_z_travel_mm: 129.0
  y_axis_motion: head
  safe_z: 69.0
working_volume:
  x_min: 0.0
  x_max: 307.0
  y_min: 0.0
  y_max: 300.0
  z_min: 0.0
  z_max: 129.0
instruments:
  camera:
    type: camera
    vendor: mount_only
    offline: true
    offset_x: 0.0
    offset_y: 0.0
    depth: 0.0
"""
DECK_YAML = "labware: {}\n"
PROTOCOL_YAML = """\
protocol:
  - home: null
  - pause:
      seconds: 0.5
      reason: observable settling
  - home: null
"""
SERVER_UUID = "5c260ea8-9589-4647-900b-d14620d831ee"


@dataclass
class Appliance:
    settings: Settings
    backend: CubOSBackend
    http: httpx.AsyncClient
    requests: list[tuple[str, str]]


@pytest_asyncio.fixture
async def appliance(tmp_path, monkeypatch):
    settings = get_settings()
    for name, value in {
        "run_dir": tmp_path / "runs",
        "data_db_path": tmp_path / "data" / "cubos.db",
        "api_token": None,
        "api_token_file": None,
        "allowed_commands": [],
        "allowed_instruments": [],
        "expected_gantry_sha256": None,
        "expected_deck_sha256": None,
    }.items():
        monkeypatch.setattr(settings, name, value)

    def forbidden_hardware(**_kwargs):
        pytest.fail("A mock SiLA run attempted the hardware execution path")

    monkeypatch.setattr(gantry_router, "run_protocol_on_session", forbidden_hardware)
    gantry_router.end_run()
    reset_run_manager()
    requests = []

    async def capture(request):
        requests.append((request.method, request.url.path))

    bundle = ProtocolBundle(GANTRY_YAML, DECK_YAML, PROTOCOL_YAML)
    config = Settings(
        server_uuid=SERVER_UUID,
        api_url="http://127.0.0.1:8742",
        poll_interval_s=0.01,
        presets=(ProtocolPreset("wire-demo", bundle, "A complete offline workflow"),),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url=config.api_url,
        event_hooks={"request": [capture]},
    ) as http:
        backend = CubOSBackend(config, client=http)
        try:
            yield Appliance(config, backend, http, requests)
        finally:
            await backend.aclose()
            reset_run_manager()
            gantry_router.end_run()


def _client(port):
    return Client(ClientConfig("127.0.0.1", port, tls=False, default_timeout=5000))


async def _finish(execution):
    async with asyncio.timeout(10):
        statuses = [status async for status in await execution.subscribe_status()]
    return statuses, await execution.get_responses()


async def _wait_run(appliance, run_id, states):
    async with asyncio.timeout(10):
        while True:
            response = await appliance.http.get(f"/api/v1/runs/{run_id}")
            if response.status_code == 200 and response.json()["state"] in states:
                return response.json()
            await asyncio.sleep(0.01)


async def _collect(stream):
    return [item async for item in stream]


@asynccontextmanager
async def _serve(appliance):
    connector = CubOSConnector(replace(appliance.settings, port=0), backend=appliance.backend)
    await connector.start()
    try:
        yield int(connector.sila_server._address.rsplit(":", 1)[1])
    finally:
        await connector.stop()


def _command(client, feature, command, *, observable=False):
    identifier = f"ai.ursalabs/cubos.appliance/{feature}/v1/Command/{command}"
    getter = client.get_observable_command if observable else client.get_unobservable_command
    return getter(identifier)


async def test_identity_feature_definitions_and_typed_catalog(appliance):
    async with _serve(appliance) as port, _client(port) as client:
        assert await client.get_server_uuid() == SERVER_UUID
        assert await client.get_server_name() == "CubOS"
        features = await client.get_implemented_features()
        for feature in ("CubStatus", "ProtocolExecution", "RunResults"):
            identifier = f"ai.ursalabs/cubos.appliance/{feature}/v1"
            assert identifier in features
            definition = ET.fromstring(await client.get_feature_definition(identifier))
            assert definition.tag.endswith("Feature")
        catalog = await _command(client, "ProtocolExecution", "ListProtocols").execute()
        assert catalog == {"Protocols": [{
            "Name": "wire-demo",
            "Description": "A complete offline workflow",
            "Mode": "mock",
            "BundleSha256": appliance.settings.presets[0].bundle.sha256,
        }]}
        available = client.get_unobservable_property(
            "ai.ursalabs/cubos.appliance/CubStatus/v1/Property/ServiceAvailable"
        )
        assert await available.read() is True


async def test_observable_mock_run_returns_progress_result_and_artifact_bytes(appliance):
    async with _serve(appliance) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "wire-demo", "RunId": "wire-run"}
        )
        progress_task = asyncio.create_task(_collect(await execution.subscribe_intermediate_responses()))
        statuses, result = await _finish(execution)
        progress = [item["Progress"] for item in await progress_task]
        assert statuses[-1].status == CommandExecutionStatus.FINISHED_SUCCESSFULLY
        assert result["RunId"] == "wire-run"
        assert result["State"] == "succeeded"
        run = json.loads(result["RunJson"])
        assert run["mock_mode"] is True
        assert isinstance(run["result"], list)
        assert progress
        assert all(item["RunId"] == "wire-run" for item in progress)
        sequences = [item["EventSequence"] for item in progress if item["EventSequence"] > 0]
        assert sequences == sorted(sequences)
        assert any(item["CompletedSteps"] == 3 and item["TotalSteps"] == 3 for item in progress)
        assert any(item["Command"] == "pause" and item["Outcome"] == "completed" for item in progress)
        reread = await _command(client, "RunResults", "GetRun").execute({"RunId": "wire-run"})
        assert json.loads(reread["RunJson"]) == run
        artifacts = await _command(client, "RunResults", "GetArtifacts").execute({"RunId": "wire-run"})
        assert {"protocol.yaml", "result.json"} <= set(artifacts["Artifacts"])
        artifact = await _command(client, "RunResults", "GetArtifact").execute(
            {"RunId": "wire-run", "ArtifactName": "protocol.yaml"}
        )
        assert artifact["Content"] == PROTOCOL_YAML.encode()


async def test_unknown_preset_and_missing_run_return_declared_errors(appliance):
    async with _serve(appliance) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "does-not-exist", "RunId": "invalid-preset"}
        )
        with pytest.raises(DefinedExecutionError) as failure:
            await _finish(execution)
        assert str(failure.value.fully_qualified_identifier).endswith("/DefinedExecutionError/InvalidProtocol")
        with pytest.raises(DefinedExecutionError) as missing:
            await _command(client, "RunResults", "GetRun").execute({"RunId": "missing"})
        assert str(missing.value.fully_qualified_identifier).endswith("/DefinedExecutionError/UnknownRun")
        assert ("POST", "/api/v1/runs") not in appliance.requests


async def test_busy_operator_run_is_rejected_without_repeating_experiment(appliance):
    payload = appliance.settings.presets[0].bundle.as_payload()
    response = await appliance.http.post("/api/v1/runs", json={**payload, "run_id": "operator-run", "mock_mode": True})
    assert response.status_code == 202
    await _wait_run(appliance, "operator-run", {"running"})
    async with _serve(appliance) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "wire-demo", "RunId": "conflicting-run"}
        )
        with pytest.raises(DefinedExecutionError) as failure:
            await _finish(execution)
        assert str(failure.value.fully_qualified_identifier).endswith("/DefinedExecutionError/CubBusy")
        assert (await appliance.http.get("/api/v1/runs/conflicting-run")).status_code == 404
        await _wait_run(appliance, "operator-run", {"succeeded"})


async def test_existing_operator_run_id_cannot_be_adopted_by_a_preset(appliance):
    payload = appliance.settings.presets[0].bundle.as_payload()
    response = await appliance.http.post("/api/v1/runs", json={**payload, "run_id": "operator-owned", "mock_mode": True})
    assert response.status_code == 202
    original = await _wait_run(appliance, "operator-owned", {"succeeded"})
    async with _serve(appliance) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "wire-demo", "RunId": "operator-owned"}
        )
        with pytest.raises(DefinedExecutionError) as failure:
            await _finish(execution)
        assert str(failure.value.fully_qualified_identifier).endswith("/DefinedExecutionError/RunConflict")
        unchanged = await _command(client, "RunResults", "GetRun").execute({"RunId": "operator-owned"})
        assert json.loads(unchanged["RunJson"]) == original


async def test_default_service_cannot_cancel_a_hardware_run(appliance, monkeypatch):
    from cubos_api.models.runs import RunRecord
    from cubos_api.services.run_store import RunStore

    def forbidden_interrupt():
        pytest.fail("Default SiLA service attempted to interrupt real hardware")

    monkeypatch.setattr(gantry_router, "request_feed_hold_interrupt", forbidden_interrupt)
    RunStore(get_settings().run_dir).write(RunRecord(
        run_id="hardware-owned", state="running", created_at=1.0, mock_mode=False,
    ))
    async with _serve(appliance) as port, _client(port) as client:
        with pytest.raises(DefinedExecutionError) as failure:
            await _command(client, "ProtocolExecution", "CancelRun").execute({"RunId": "hardware-owned"})
        assert str(failure.value.fully_qualified_identifier).endswith("/DefinedExecutionError/InvalidRequest")
        assert ("POST", "/api/v1/runs/hardware-owned/cancel") not in appliance.requests


async def test_disconnect_then_resume_same_id_does_not_repeat_run(appliance):
    async with _serve(appliance) as port:
        async with _client(port) as client:
            execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
                {"ProtocolName": "wire-demo", "RunId": "recovered-run"}
            )
            await _wait_run(appliance, "recovered-run", {"running"})
            execution.cancel()
        finished = await _wait_run(appliance, "recovered-run", {"succeeded"})
        async with _client(port) as reconnected:
            execution = await _command(reconnected, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
                {"ProtocolName": "wire-demo", "RunId": "recovered-run"}
            )
            _, result = await _finish(execution)
            assert json.loads(result["RunJson"])["started_at"] == finished["started_at"]
            reread = await _command(reconnected, "RunResults", "GetRun").execute({"RunId": "recovered-run"})
            assert json.loads(reread["RunJson"])["finished_at"] == finished["finished_at"]
        events = (await appliance.http.get("/api/v1/runs/recovered-run/events")).json()["events"]
        lifecycle = [event["state"] for event in events if event["kind"] == "lifecycle"]
        assert lifecycle == ["queued", "running", "succeeded"]


async def test_cancel_request_is_distinct_from_confirmed_cancellation(appliance):
    async with _serve(appliance) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "wire-demo", "RunId": "cancel-requested"}
        )
        await _wait_run(appliance, "cancel-requested", {"running"})
        response = await _command(client, "ProtocolExecution", "CancelRun").execute({"RunId": "cancel-requested"})
        assert response == {"State": "cancel_requested"}
        _, result = await _finish(execution)
        assert result["State"] == "succeeded"
        events = (await appliance.http.get("/api/v1/runs/cancel-requested/events")).json()["events"]
        assert "cancel_requested" in [event["state"] for event in events]


async def test_execution_failure_is_declared_and_original_error_is_retrievable(appliance, monkeypatch):
    from cubos_api.services import run_manager

    def fail_mock(**_kwargs):
        raise RuntimeError("simulated acquisition failed")

    monkeypatch.setattr(run_manager, "_mock_execute", fail_mock)
    async with _serve(appliance) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "wire-demo", "RunId": "failed-run"}
        )
        with pytest.raises(DefinedExecutionError) as failure:
            await _finish(execution)
        assert str(failure.value.fully_qualified_identifier).endswith("/DefinedExecutionError/RunFailed")
        reread = await _command(client, "RunResults", "GetRun").execute({"RunId": "failed-run"})
        run = json.loads(reread["RunJson"])
        assert run["state"] == "failed"
        assert run["error"] == "RuntimeError: simulated acquisition failed"


async def test_invalid_run_id_is_rejected_before_submission(appliance):
    async with _serve(appliance) as port, _client(port) as client:
        with pytest.raises((ValidationError, DefinedExecutionError)):
            execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
                {"ProtocolName": "wire-demo", "RunId": "../escape"}
            )
            await _finish(execution)
        assert ("POST", "/api/v1/runs") not in appliance.requests


async def test_service_restart_recovers_original_run_without_submission(appliance):
    async with _serve(appliance) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "wire-demo", "RunId": "restart-run"}
        )
        _, result = await _finish(execution)
    before = appliance.requests.count(("POST", "/api/v1/runs"))
    async with _serve(appliance) as port, _client(port) as client:
        recovered = await _command(client, "RunResults", "GetRun").execute({"RunId": "restart-run"})
        assert recovered == {"RunJson": result["RunJson"]}
        assert appliance.requests.count(("POST", "/api/v1/runs")) == before == 1


async def test_large_artifact_uses_interoperable_sila_binary_transfer(appliance):
    protocol = PROTOCOL_YAML + "# " + "x" * (2**21) + "\n"
    preset = replace(appliance.settings.presets[0], bundle=ProtocolBundle(GANTRY_YAML, DECK_YAML, protocol))
    config = replace(appliance.settings, presets=(preset,))
    large = replace(appliance, settings=config, backend=CubOSBackend(config, client=appliance.http))
    async with _serve(large) as port, _client(port) as client:
        execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
            {"ProtocolName": "wire-demo", "RunId": "large-artifact"}
        )
        await _finish(execution)
        artifact = await _command(client, "RunResults", "GetArtifact").execute(
            {"RunId": "large-artifact", "ArtifactName": "protocol.yaml"}
        )
        assert artifact["Content"] == protocol.encode()


async def test_lost_submission_reply_recovers_same_run_without_retrying_post(appliance):
    class LostReply(httpx.AsyncBaseTransport):
        posts = 0

        def __init__(self):
            self.inner = httpx.ASGITransport(app=create_app())

        async def handle_async_request(self, request):
            response = await self.inner.handle_async_request(request)
            if request.method == "POST" and request.url.path == "/api/v1/runs":
                self.posts += 1
                assert response.status_code == 202
                await response.aclose()
                raise httpx.ReadError("submission response lost", request=request)
            return response

        async def aclose(self):
            await self.inner.aclose()

    transport = LostReply()
    async with httpx.AsyncClient(transport=transport) as http:
        uncertain = replace(appliance, backend=CubOSBackend(appliance.settings, client=http))
        async with _serve(uncertain) as port, _client(port) as client:
            execution = await _command(client, "ProtocolExecution", "ExecuteProtocol", observable=True).execute(
                {"ProtocolName": "wire-demo", "RunId": "uncertain-run"}
            )
            _, result = await _finish(execution)
            assert result["RunId"] == "uncertain-run"
            assert result["State"] == "succeeded"
            assert transport.posts == 1


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL is needed to create the test certificate")
async def test_configured_certificate_connects_with_explicit_client_trust(appliance, tmp_path):
    certificate = tmp_path / "server.pem"
    private_key = tmp_path / "server.key"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(private_key), "-out", str(certificate), "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )
    secured = replace(appliance, settings=replace(appliance.settings, certificate=certificate, private_key=private_key))
    async with _serve(secured) as port:
        config = ClientConfig("127.0.0.1", port, tls=True, root_certificates=certificate.read_bytes(), default_timeout=5000)
        async with Client(config) as client:
            assert await client.get_server_uuid() == SERVER_UUID
            catalog = await _command(client, "ProtocolExecution", "ListProtocols").execute()
            assert catalog["Protocols"][0]["Name"] == "wire-demo"
