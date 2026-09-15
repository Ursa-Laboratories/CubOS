"""Active-learning campaign editing and lifecycle endpoints."""
import uuid

from fastapi import APIRouter, HTTPException
from cubos.gantry.session import GantryNotConnectedError, InterruptFeedHoldTimeoutError
from cubos_api.config import get_settings
from cubos_api.models.campaigns import (
    CampaignRecord, CampaignSpec, CampaignSubmission, ColorCampaignSetup,
    ColorTargetRequest, Observation,
)
from cubos_api.models.runs import RunRecord, RunSubmission
from cubos_api.services.color_campaign import build_color_campaign, target_protocol
from cubos_api.services.campaign_manager import get_campaign_manager
from cubos_api.services.run_manager import RunConflictError, get_run_manager
from cubos_api.services.yaml_io import resolve_config_path

router = APIRouter(prefix="/api/v1/campaigns", tags=["active-learning"])


@router.get("", response_model=list[CampaignRecord])
def list_campaigns():
    return get_campaign_manager().list()


@router.post("/validate")
def validate_campaign(body: CampaignSubmission):
    return get_campaign_manager().validate(body.spec)


@router.post("/color-target", response_model=RunRecord, status_code=202)
def read_color_target(body: ColorTargetRequest):
    """Submit a native run that reads Lab from the selected target well."""
    settings = get_settings()
    try:
        gantry = resolve_config_path(settings.configs_dir, "gantry", body.gantry_file).read_text()
        deck = resolve_config_path(settings.configs_dir, "deck", body.deck_file).read_text()
        submission = RunSubmission(
            run_id=f"color-target-{uuid.uuid4().hex[:12]}",
            gantry_config=gantry,
            deck_config=deck,
            protocol_yaml=target_protocol(
                body.target_well, body.camera_instrument, body.roi_fraction
            ),
            mock_mode=body.mock_mode,
            metadata={"active_learning_target": body.target_well},
        )
        return get_run_manager().submit(submission)
    except RunConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, f"{type(exc).__name__}: {exc}") from exc


@router.get("/color-target/{run_id}", response_model=RunRecord)
def get_color_target(run_id: str):
    record = get_run_manager().get(run_id)
    if record is None or not record.metadata.get("active_learning_target"):
        raise HTTPException(404, "Color target run not found")
    return record


@router.post("/color-setup", response_model=CampaignSpec)
def prepare_color_campaign(body: ColorCampaignSetup):
    """Create a generated candidate protocol and complete campaign draft."""
    settings = get_settings()
    return build_color_campaign(body, settings.configs_dir / "protocol")


@router.post("", response_model=CampaignRecord, status_code=202)
def start_campaign(body: CampaignSubmission):
    try:
        return get_campaign_manager().start(body.spec)
    except RunConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, f"{type(exc).__name__}: {exc}") from exc


@router.get("/{campaign_id}", response_model=CampaignRecord)
def get_campaign(campaign_id: str):
    try:
        return get_campaign_manager().get(campaign_id)
    except KeyError as exc:
        raise HTTPException(404, "Campaign not found") from exc


@router.post("/{campaign_id}/observation", response_model=CampaignRecord)
def observe(campaign_id: str, body: Observation):
    try:
        return get_campaign_manager().observe(campaign_id, body.value)
    except KeyError as exc:
        raise HTTPException(404, "Campaign not found") from exc
    except RunConflictError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{campaign_id}/{action}", response_model=CampaignRecord)
def control(campaign_id: str, action: str):
    if action not in {"pause", "resume", "stop", "cancel"}:
        raise HTTPException(404, "Unknown campaign action")
    try:
        return get_campaign_manager().control(campaign_id, action)
    except KeyError as exc:
        raise HTTPException(404, "Campaign not found") from exc
    except RunConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except GantryNotConnectedError as exc:
        raise HTTPException(400, "Stop was requested, but the gantry is disconnected and immediate cancellation could not be confirmed.") from exc
    except InterruptFeedHoldTimeoutError as exc:
        raise HTTPException(409, "Stop was requested, but feed hold did not confirm in time. Inspect the controller before further actions.") from exc
