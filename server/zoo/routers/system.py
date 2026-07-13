"""Versioned, hardware-safe CubOS appliance discovery endpoints."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Dict, List

from fastapi import APIRouter
from instruments.registry import get_supported_types, get_supported_vendors
from pydantic import BaseModel
from protocol_engine.registry import CommandRegistry

# Register CubOS protocol commands without connecting to hardware.
import protocol_engine.commands  # noqa: F401


API_VERSION = "v1"
SERVICE_NAME = "cubos-server"

router = APIRouter(prefix="/api/v1", tags=["cubos-v1"])


class HealthResponse(BaseModel):
    status: str
    service: str
    api_version: str


class VersionResponse(BaseModel):
    service: str
    api_version: str
    zoo_version: str
    cubos_version: str
    build_version: str | None = None
    image_digest: str | None = None


class CapabilitiesResponse(BaseModel):
    api_version: str
    commands: List[str]
    instruments: Dict[str, List[str]]


def _distribution_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report API readiness without connecting to or probing hardware."""
    return HealthResponse(status="ok", service=SERVICE_NAME, api_version=API_VERSION)


@router.get("/version", response_model=VersionResponse)
def get_version() -> VersionResponse:
    """Return release identity for diagnostics and update verification."""
    return VersionResponse(
        service=SERVICE_NAME,
        api_version=API_VERSION,
        zoo_version=_distribution_version("zoo"),
        cubos_version=_distribution_version("cubos"),
        build_version=os.environ.get("CUB_BUILD_VERSION"),
        image_digest=os.environ.get("CUB_IMAGE_DIGEST"),
    )


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities() -> CapabilitiesResponse:
    """Reflect installed CubOS commands and instrument vendor support."""
    instruments = {
        instrument_type: get_supported_vendors(instrument_type)
        for instrument_type in get_supported_types()
    }
    return CapabilitiesResponse(
        api_version=API_VERSION,
        commands=CommandRegistry.instance().command_names,
        instruments=instruments,
    )
