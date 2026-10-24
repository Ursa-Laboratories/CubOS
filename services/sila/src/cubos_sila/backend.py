"""Asynchronous delegation to the sole hardware owner, the CubOS HTTP API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any
from urllib.parse import quote

import httpx

from .config import ProtocolPreset, Settings
from .errors import BackendError


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class CubOSBackend:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(follow_redirects=False)
        self._owns_client = client is None
        self._presets = {preset.name: preset for preset in settings.presets}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _run_path(self, run_id: str) -> str:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise BackendError("invalid_request", "run_id must use 1–128 letters, digits, '.', '_' or '-' and start with a letter or digit")
        return f"/api/v1/runs/{run_id}"

    def _safe_message(self, message: str) -> str:
        token = self.settings.api_token
        return message.replace(token, "[redacted]") if token else message

    async def _bytes(
        self, method: str, path: str, *, payload: dict | None = None,
        params: dict | None = None, limit: int | None = None,
        missing: str = "unknown_run",
    ) -> bytes:
        headers = {}
        if self.settings.api_token:
            headers["Authorization"] = f"Bearer {self.settings.api_token}"
        bound = self.settings.max_response_bytes if limit is None else limit
        try:
            async with asyncio.timeout(self.settings.request_timeout_s):
                async with self._client.stream(
                    method, self.settings.api_url.rstrip("/") + path,
                    json=payload, params=params, headers=headers,
                    timeout=self.settings.request_timeout_s, follow_redirects=False,
                ) as response:
                    if response.status_code >= 400:
                        error_content = bytearray()
                        async for chunk in response.aiter_bytes():
                            error_content.extend(chunk[: max(0, min(bound, 8192) - len(error_content))])
                            if len(error_content) >= min(bound, 8192):
                                break
                        detail = "CubOS API request failed"
                        try:
                            body = json.loads(error_content)
                            if isinstance(body, dict):
                                detail = str(body.get("detail", detail))[:2000]
                        except (ValueError, UnicodeError):
                            pass
                        code = {
                            400: "invalid_protocol" if path == "/api/v1/runs" else "invalid_request",
                            401: "auth", 403: "auth", 404: missing,
                            409: "busy", 422: "invalid_protocol" if method == "POST" and path == "/api/v1/runs" else "invalid_request",
                        }.get(response.status_code, "unavailable")
                        raise BackendError(code, self._safe_message(detail), status_code=response.status_code)
                    if not 200 <= response.status_code < 300:
                        raise BackendError("unavailable", "CubOS API returned an unexpected redirect or response")
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > bound:
                        code = "artifact_too_large" if limit is not None else "unavailable"
                        raise BackendError(code, "CubOS response exceeds the configured byte limit")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > bound:
                            code = "artifact_too_large" if limit is not None else "unavailable"
                            raise BackendError(code, "CubOS response exceeds the configured byte limit")
                        content.extend(chunk)
                    return bytes(content)
        except (httpx.HTTPError, TimeoutError):
            raise BackendError("unavailable", "CubOS API request did not complete; inspect the original run ID before retrying") from None

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        content = await self._bytes(method, path, **kwargs)
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            raise BackendError("unavailable", "CubOS API returned invalid JSON") from None
        if not isinstance(value, dict):
            raise BackendError("unavailable", "CubOS API returned an invalid response object")
        return value

    async def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "api_available": False, "hardware_connected": None,
            "execution_state": "unknown", "active_run_id": None,
        }
        paths = {
            "health": "/api/v1/health", "version": "/api/v1/version",
            "capabilities": "/api/v1/capabilities", "position": "/api/v1/gantry/position",
        }
        observations = await asyncio.gather(
            *(self._json("GET", path) for path in paths.values()), return_exceptions=True,
        )
        for name, value in zip(paths, observations):
            if isinstance(value, BackendError):
                if value.code == "auth":
                    raise value
                result[name] = {"error": value.code}
            elif isinstance(value, BaseException):
                raise value
            else:
                result[name] = value
                if name == "health":
                    result["api_available"] = value.get("status") == "ok"
                elif name == "position" and type(value.get("connected")) is bool:
                    result["hardware_connected"] = value["connected"]
        return result

    async def list_protocols(self) -> list[dict[str, Any]]:
        return [
            {"name": preset.name, "description": preset.description,
             "mode": "mock" if preset.mock_mode else "hardware", "bundle_sha256": preset.bundle.sha256}
            for preset in self.settings.presets
        ]

    def _verify_submission(
        self, record: dict[str, Any], run_id: str, preset: ProtocolPreset,
    ) -> dict[str, Any]:
        metadata = record.get("metadata")
        provenance = metadata.get("cubos_sila") if isinstance(metadata, dict) else None
        expected = {
            "server_uuid": self.settings.server_uuid, "preset": preset.name,
            "bundle_sha256": preset.bundle.sha256, "mock_mode": preset.mock_mode,
        }
        if (
            record.get("run_id") != run_id
            or record.get("mock_mode") is not preset.mock_mode
            or not isinstance(provenance, dict)
            or any(provenance.get(key) != value for key, value in expected.items())
        ):
            raise BackendError("conflict", "run_id already belongs to a different request; retrieve it without resubmitting")
        digests = record.get("digests")
        if digests is not None:
            expected_digests = {
                name: hashlib.sha256(content.encode("utf-8")).hexdigest()
                for name, content in zip(
                    ("gantry_sha256", "deck_sha256", "protocol_sha256"),
                    (preset.bundle.gantry_config, preset.bundle.deck_config, preset.bundle.protocol_yaml),
                )
            }
            if not isinstance(digests, dict) or any(digests.get(key) != value for key, value in expected_digests.items()):
                raise BackendError("conflict", "stored run inputs do not match the configured protocol bundle")
        return record

    async def execute_protocol(
        self, protocol_name: str, run_id: str, *, execution_id: str | None = None,
    ) -> dict[str, Any]:
        path = self._run_path(run_id)
        preset = self._presets.get(protocol_name)
        if preset is None:
            raise BackendError("invalid_protocol", "unknown configured protocol preset")
        if not preset.mock_mode and not self.settings.allow_hardware:
            raise BackendError("invalid_request", "hardware execution requires explicit server authorization")
        provenance: dict[str, Any] = {
            "server_uuid": self.settings.server_uuid,
            "preset": preset.name, "bundle_sha256": preset.bundle.sha256,
            "mock_mode": preset.mock_mode,
        }
        if execution_id is not None:
            provenance["execution_id"] = execution_id
        payload = {
            "run_id": run_id, **preset.bundle.as_payload(), "mock_mode": preset.mock_mode,
            "metadata": {"cubos_sila": provenance},
        }
        if len(json.dumps(payload).encode("utf-8")) > self.settings.max_response_bytes:
            raise BackendError("invalid_protocol", "preset submission exceeds the configured byte limit")
        try:
            record = await self._json("POST", "/api/v1/runs", payload=payload)
        except BackendError as error:
            if error.code not in {"busy", "unavailable"}:
                raise
            try:
                existing = await self._json("GET", path)
            except BackendError as lookup_error:
                if lookup_error.code == "auth":
                    raise
                raise error from None
            return self._verify_submission(existing, run_id, preset)
        return self._verify_submission(record, run_id, preset)

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._json("GET", self._run_path(run_id))

    async def get_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        if type(after) is not int or after < 0:
            raise BackendError("invalid_request", "event cursor must be a nonnegative integer")
        result = await self._json("GET", self._run_path(run_id) + "/events", params={"after": after})
        events = result.get("events")
        if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
            raise BackendError("unavailable", "CubOS API returned invalid events")
        return events

    async def get_plan(self, run_id: str) -> list[dict[str, Any]]:
        result = await self._json("GET", self._run_path(run_id) + "/plan")
        steps = result.get("steps")
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise BackendError("unavailable", "CubOS API returned an invalid plan")
        return steps

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id)
        record = await self.get_run(run_id)
        if record.get("mock_mode") is not True and not self.settings.allow_hardware:
            raise BackendError("invalid_request", "cancelling a hardware run requires explicit server authorization")
        return await self._json("POST", path + "/cancel", payload={})

    async def get_artifacts(self, run_id: str) -> list[str]:
        result = await self._json("GET", self._run_path(run_id) + "/artifacts")
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
            raise BackendError("unavailable", "CubOS API returned an invalid artifact list")
        return artifacts

    async def get_artifact(self, run_id: str, artifact_id: str) -> bytes:
        path = self._run_path(run_id)
        if not artifact_id or artifact_id in {".", ".."} or "/" in artifact_id or "\\" in artifact_id:
            raise BackendError("invalid_request", "artifact_id must be a single artifact name")
        return await self._bytes(
            "GET", path + "/artifacts/" + quote(artifact_id, safe=""),
            limit=self.settings.max_artifact_bytes, missing="unknown_artifact",
        )
