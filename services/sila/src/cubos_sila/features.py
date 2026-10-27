"""Code-first CubOS SiLA feature definitions."""

import asyncio
import dataclasses
import datetime
import json
from typing import Annotated

from unitelabs.cdk import sila

from .errors import BACKEND_ERRORS, RunCancelled, RunFailed, backend_call


RunId = Annotated[str, sila.constraints.Pattern(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")]


@dataclasses.dataclass
class ProtocolInfo(sila.Dataclass):
    """A configured protocol preset and its execution mode."""

    name: str
    description: str
    mode: str
    bundle_sha256: str


@dataclasses.dataclass
class RunProgress(sila.Dataclass):
    """Authoritative run state and ordered CubOS step observations."""

    run_id: str
    state: str
    event_sequence: int
    step_index: int
    command: str
    substep: str
    outcome: str
    completed_steps: int
    total_steps: int
    message: str


class CubStatus(sila.Feature):
    """CubOS API availability and hardware state, with unknown reported explicitly."""

    def __init__(self, backend):
        super().__init__(originator="ai.ursalabs", category="cubos.appliance", version="1.0", maturity_level="Draft")
        self.backend = backend

    @sila.UnobservableProperty(errors=BACKEND_ERRORS)
    async def software_version(self) -> str:
        """The software version reported by CubOS, or unknown when unavailable."""
        version = (await backend_call(self.backend.status())).get("version")
        return str(version.get("cubos_version") or "unknown") if isinstance(version, dict) else "unknown"

    @sila.UnobservableProperty(errors=BACKEND_ERRORS)
    async def service_available(self) -> bool:
        """Whether the CubOS API is reachable and healthy; this does not imply hardware readiness."""
        return bool((await backend_call(self.backend.status())).get("api_available", False))

    @sila.UnobservableProperty(errors=BACKEND_ERRORS)
    async def hardware_connection_state(self) -> str:
        """Connected, disconnected, or unknown according to the CubOS runtime."""
        connected = (await backend_call(self.backend.status())).get("hardware_connected")
        return "connected" if connected is True else "disconnected" if connected is False else "unknown"

    @sila.UnobservableProperty(errors=BACKEND_ERRORS)
    async def execution_state(self) -> str:
        """The authoritative CubOS execution state, or unknown when unavailable."""
        return str((await backend_call(self.backend.status())).get("execution_state") or "unknown")

    @sila.UnobservableProperty(errors=BACKEND_ERRORS)
    async def active_run_id(self) -> str:
        """The active CubOS run identifier, or an empty string when none is known."""
        return str((await backend_call(self.backend.status())).get("active_run_id") or "")


class ProtocolExecution(sila.Feature):
    """Run configured CubOS presets with caller-owned stable run identifiers.

    Closing an observation does not cancel a run. After a service restart, use
    RunResults.GetRun with the original RunId; command handles are not restored.
    """

    def __init__(self, backend, poll_interval_s: float = 0.25):
        super().__init__(originator="ai.ursalabs", category="cubos.appliance", version="1.0", maturity_level="Draft")
        self.backend = backend
        self.poll_interval_s = poll_interval_s

    @sila.UnobservableCommand(errors=BACKEND_ERRORS)
    async def list_protocols(self) -> list[ProtocolInfo]:
        """List configured protocol presets.

        Returns:
          Protocols: Preset names, descriptions, modes, and immutable bundle digests.
        """
        return [ProtocolInfo(**preset) for preset in await backend_call(self.backend.list_protocols())]

    @sila.ObservableCommand(errors=(*BACKEND_ERRORS, RunFailed, RunCancelled), auto_start=False, lifetime=3600)
    async def execute_protocol(
        self,
        protocol_name: str,
        run_id: RunId,
        *,
        status: sila.Status,
        intermediate: sila.Intermediate[RunProgress],
    ) -> tuple[str, str, str]:
        """Submit once or resume observing the same verified CubOS run.

        Args:
          ProtocolName: Name returned by ListProtocols.
          RunId: Caller-generated stable identifier. Reuse it after an uncertain response.

        Yields:
          Progress: Run state and ordered event information. StepIndex and TotalSteps are -1 when unknown.

        Returns:
          RunId: The persistent CubOS run identifier.
          State: The confirmed terminal state succeeded.
          RunJson: Complete CubOS run record as JSON.
        """
        execution_id = status.command_execution.command_execution_uuid
        run = await backend_call(self.backend.execute_protocol(protocol_name, run_id, execution_id=execution_id))
        completed: set[int] = set()
        cursor = 0
        total = -1
        intermediate.send(RunProgress(run_id, run["state"], 0, -1, "", "", "", 0, total, "Run accepted"))
        plan = await backend_call(self.backend.get_plan(run_id))
        total = len(plan)
        previous_state = None
        while True:
            run = await backend_call(self.backend.get_run(run_id))
            events = await backend_call(self.backend.get_events(run_id, after=cursor))
            state = run["state"]
            if state in ("running", "cancel_requested"):
                status.start()
            for event in events:
                sequence = int(event["sequence"])
                if sequence <= cursor:
                    continue
                cursor = sequence
                data = event.get("data") or {}
                index = data.get("index", -1)
                if event.get("kind") == "step" and not data.get("substep") and data.get("outcome") in ("completed", "skipped"):
                    completed.add(index)
                intermediate.send(RunProgress(
                    run_id, state, cursor, index, str(data.get("command") or ""),
                    str(data.get("substep") or ""), str(data.get("outcome") or ""),
                    len(completed), total, str(event.get("message") or ""),
                ))
            if not events or state != previous_state:
                intermediate.send(RunProgress(run_id, state, cursor, -1, "", "", "", len(completed), total, "Run state"))
            previous_state = state
            status.update(
                progress=min(len(completed) / total, 1.0) if total > 0 and completed else None,
                updated_lifetime=datetime.timedelta(hours=1),
            )
            if state == "succeeded":
                return run_id, state, json.dumps(run, ensure_ascii=False, allow_nan=False)
            if state == "failed":
                raise RunFailed(f"Run {run_id} failed: {run.get('error') or 'See RunResults.GetRun'}")
            if state == "cancelled":
                raise RunCancelled(f"Run {run_id} was cancelled")
            await asyncio.sleep(self.poll_interval_s)

    @sila.UnobservableCommand(errors=BACKEND_ERRORS)
    async def cancel_run(self, run_id: RunId) -> str:
        """Request cancellation; mounted instrument calls may continue until they return.

        Args:
          RunId: The persistent CubOS run identifier.

        Returns:
          State: Authoritative state after requesting cancellation. cancel_requested is not cancelled.
        """
        return (await backend_call(self.backend.cancel_run(run_id)))["state"]


class RunResults(sila.Feature):
    """Retrieve persisted run records and artifact contents without repeating a protocol."""

    def __init__(self, backend):
        super().__init__(originator="ai.ursalabs", category="cubos.appliance", version="1.0", maturity_level="Draft")
        self.backend = backend

    @sila.UnobservableCommand(errors=BACKEND_ERRORS)
    async def get_run(self, run_id: RunId) -> str:
        """Retrieve a run record, including its state, metadata, result, and error.

        Args:
          RunId: The persistent CubOS run identifier.

        Returns:
          RunJson: Complete CubOS run record as JSON.
        """
        return json.dumps(await backend_call(self.backend.get_run(run_id)), ensure_ascii=False, allow_nan=False)

    @sila.UnobservableCommand(errors=BACKEND_ERRORS)
    async def get_artifacts(self, run_id: RunId) -> list[str]:
        """List artifacts persisted for a run.

        Args:
          RunId: The persistent CubOS run identifier.

        Returns:
          Artifacts: Artifact names accepted by GetArtifact.
        """
        return await backend_call(self.backend.get_artifacts(run_id))

    @sila.UnobservableCommand(errors=BACKEND_ERRORS)
    async def get_artifact(self, run_id: RunId, artifact_name: str) -> bytes:
        """Retrieve bounded artifact contents using SiLA Binary, including its transfer service.

        Args:
          RunId: The persistent CubOS run identifier.
          ArtifactName: An exact name returned by GetArtifacts.

        Returns:
          Content: The artifact bytes, transferred through SiLA without separate HTTP credentials.
        """
        return await backend_call(self.backend.get_artifact(run_id, artifact_name))
