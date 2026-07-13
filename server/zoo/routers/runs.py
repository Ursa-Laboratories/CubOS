"""Asynchronous, addressable CubOS protocol runs under the versioned API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from gantry.session import (
    GantryNotConnectedError,
    InterruptFeedHoldTimeoutError,
)

from zoo.models.runs import (
    RunArtifactsResponse,
    RunEventsResponse,
    RunRecord,
    RunSubmission,
)
from zoo.services.run_manager import (
    RunConflictError,
    RunPolicyError,
    get_run_manager,
)


router = APIRouter(prefix="/api/v1/runs", tags=["cubos-runs-v1"])


@router.post("", response_model=RunRecord, status_code=202)
def submit_run(body: RunSubmission, response: Response) -> RunRecord:
    try:
        record = get_run_manager().submit(body)
    except RunConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (RunPolicyError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    response.headers["Location"] = f"/api/v1/runs/{record.run_id}"
    return record


@router.get("/{run_id}", response_model=RunRecord)
def get_run(run_id: str) -> RunRecord:
    record = get_run_manager().get(run_id)
    if record is None:
        raise HTTPException(404, f"run {run_id!r} was not found")
    return record


@router.post("/{run_id}/cancel", response_model=RunRecord, status_code=202)
def cancel_run(run_id: str) -> RunRecord:
    try:
        return get_run_manager().cancel(run_id)
    except KeyError as exc:
        raise HTTPException(404, f"run {run_id!r} was not found") from exc
    except RunConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except InterruptFeedHoldTimeoutError:
        record = get_run_manager().get(run_id)
        assert record is not None
        return record
    except GantryNotConnectedError as exc:
        raise HTTPException(400, "gantry is not connected") from exc


@router.get("/{run_id}/events", response_model=RunEventsResponse)
def get_run_events(run_id: str, after: int = 0) -> RunEventsResponse:
    manager = get_run_manager()
    if manager.get(run_id) is None:
        raise HTTPException(404, f"run {run_id!r} was not found")
    events = [event for event in manager.events(run_id) if event.sequence > after]
    return RunEventsResponse(run_id=run_id, events=events)


@router.get("/{run_id}/artifacts", response_model=RunArtifactsResponse)
def get_run_artifacts(run_id: str) -> RunArtifactsResponse:
    record = get_run_manager().get(run_id)
    if record is None:
        raise HTTPException(404, f"run {run_id!r} was not found")
    return RunArtifactsResponse(run_id=run_id, artifacts=record.artifacts)


@router.get("/{run_id}/artifacts/{name}", response_class=FileResponse)
def download_run_artifact(run_id: str, name: str) -> FileResponse:
    manager = get_run_manager()
    if manager.get(run_id) is None:
        raise HTTPException(404, f"run {run_id!r} was not found")
    path = manager.store.artifact_path(run_id, name)
    if path is None:
        raise HTTPException(404, f"artifact {name!r} was not found")
    return FileResponse(path, filename=name)
