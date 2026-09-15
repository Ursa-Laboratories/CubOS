"""HTTP models for opt-in live camera monitoring."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CameraMonitorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CameraResolution(CameraMonitorModel):
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class CameraMonitorRequest(CameraMonitorModel):
    instrument: str = Field(min_length=1, max_length=80)


class CameraMonitorLeaseRequest(CameraMonitorRequest):
    lease_id: str = Field(min_length=1, max_length=80)


class NormalizedPoint(CameraMonitorModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class CameraMonitorStatus(CameraMonitorModel):
    instrument: str
    state: Literal["stopped", "running", "failed"]
    connected: bool
    lease_id: str | None = None
    lease_expires_at: float | None = None
    subscriber_count: int = 0
    camera_id: int | None = None
    requested_resolution: CameraResolution | None = None
    actual_resolution: CameraResolution | None = None
    requested_pixel_format: str | None = None
    actual_pixel_format: str | None = None
    frame_id: int | None = None
    received_at: float | None = None
    frame_age_seconds: float | None = None
    image_url: str | None = None
    control_fingerprint: str | None = None
    capture_profile: dict[str, Any] | None = None
    run_id: str | None = None
    campaign_id: str | None = None
    trial_number: int | None = None
    step_index: int | None = None
    step_command: str | None = None
    step_substep: str | None = None
    expected_well: str | None = None
    expected_center: NormalizedPoint | None = None
    expected_center_source: Literal[
        "operator_selected", "registered_calibration"
    ] | None = None
    well_identity_verification: Literal["not_verified_by_cv"] = "not_verified_by_cv"
    roi: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    processing_profile: dict[str, Any] | None = None
    analysis_source_image_path: str | None = None
    analysis_image_url: str | None = None
    analysis_source_run_id: str | None = None
    analysis_source_well: str | None = None
    analysis_source_frame_id: int | None = None
    analysis_source_received_at: float | None = None
    analysis_is_current_frame: bool = False
    latest_analysis: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class CameraControlValue(CameraMonitorModel):
    supported: bool | None
    value: float | None = None
    error: str | None = None


class CameraControlsResponse(CameraMonitorModel):
    instrument: str
    controls: dict[str, CameraControlValue]
    control_fingerprint: str


class CameraControlUpdates(CameraMonitorModel):
    exposure: float | None = None
    white_balance: float | None = None
    focus: float | None = None
    brightness: float | None = None


class SetCameraControlsRequest(CameraMonitorModel):
    instrument: str = Field(min_length=1, max_length=80)
    controls: CameraControlUpdates


__all__ = [
    "CameraControlsResponse",
    "CameraMonitorLeaseRequest",
    "CameraMonitorRequest",
    "CameraMonitorStatus",
    "SetCameraControlsRequest",
]
