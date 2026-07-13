"""Data router: browse stored campaign outputs and export CubOS archives."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from sqlite3 import DatabaseError

from data import (
    CampaignNotFoundError,
    DataDatabaseNotFoundError,
    DataExportError,
    DataSchemaError,
    MeasurementDataError,
    MeasurementExportNotFoundError,
    export_campaign_asmi_zip as cubos_export_campaign_asmi_zip,
    export_campaign_measurements_zip as cubos_export_campaign_measurements_zip,
    list_campaign_summaries,
)
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from zoo.config import get_settings

router = APIRouter(prefix="/api/data", tags=["data"])


class CampaignSummary(BaseModel):
    campaign_id: int
    campaign_description: str
    created_at: str
    latest_measurement_at: str | None
    experiment_count: int
    well_count: int
    measurement_count: int
    measurement_counts: dict[str, int]
    asmi_measurement_count: int


@router.get("/campaigns")
def list_campaigns() -> list[CampaignSummary]:
    """Return campaign rows with simple measurement metadata."""
    try:
        summaries = list_campaign_summaries(_data_db_path())
    except DataDatabaseNotFoundError:
        return []
    except DataExportError as exc:
        raise _data_http_exception(exc) from exc
    except DatabaseError as exc:
        raise _unreadable_database_exception(exc) from exc
    return [CampaignSummary(**asdict(summary)) for summary in summaries]


@router.get("/campaigns/{campaign_id}/measurements.zip")
def export_campaign_measurements_zip(campaign_id: int) -> Response:
    """Export non-empty instrument measurement tables for a campaign as CSV."""
    try:
        content = cubos_export_campaign_measurements_zip(
            _data_db_path(),
            campaign_id,
        )
    except DataExportError as exc:
        raise _data_http_exception(exc) from exc
    except DatabaseError as exc:
        raise _unreadable_database_exception(exc) from exc
    filename = f"campaign_{campaign_id}_measurements.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/campaigns/{campaign_id}/asmi.zip")
def export_campaign_asmi_zip(campaign_id: int) -> Response:
    """Export a campaign's ASMI measurements as raw CSV files plus metadata."""
    try:
        content = cubos_export_campaign_asmi_zip(_data_db_path(), campaign_id)
    except DataExportError as exc:
        raise _data_http_exception(exc) from exc
    except DatabaseError as exc:
        raise _unreadable_database_exception(exc) from exc
    filename = f"campaign_{campaign_id}_asmi_raw_csvs.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/experiments")
def list_experiments() -> list[CampaignSummary]:
    """Backward-compatible alias for campaign results."""
    return list_campaigns()


def _data_db_path() -> Path:
    return get_settings().data_db_path.expanduser().resolve()


def _data_http_exception(exc: DataExportError) -> HTTPException:
    if isinstance(
        exc,
        (
            DataDatabaseNotFoundError,
            CampaignNotFoundError,
            MeasurementExportNotFoundError,
        ),
    ):
        return HTTPException(404, str(exc))
    if isinstance(exc, (DataSchemaError, MeasurementDataError)):
        return HTTPException(400, str(exc))
    return HTTPException(500, str(exc))


def _unreadable_database_exception(exc: DatabaseError) -> HTTPException:
    return HTTPException(400, f"Data database is unreadable: {exc}")
