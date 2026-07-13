"""Raw YAML read/write endpoints for direct editing."""

from collections.abc import MutableMapping

import yaml
from fastapi import APIRouter, HTTPException
from gantry.yaml_schema import GantryYamlSchema
from pydantic import BaseModel
from pydantic import ValidationError

from zoo.config import get_settings
from zoo.services.yaml_io import (
    atomic_write_text,
    classify_config,
    resolve_config_path,
    safe_filename,
)

router = APIRouter(prefix="/api/raw", tags=["raw"])
_CONFIG_KINDS = ("deck", "gantry", "protocol")


class RawYaml(BaseModel):
    content: str


def _resolve_raw_path(filename: str, data: object | None = None):
    settings = get_settings()
    filename = safe_filename(filename)

    for kind in _CONFIG_KINDS:
        if not (settings.configs_dir / kind).is_dir():
            continue
        path = resolve_config_path(settings.configs_dir, kind, filename)
        if path.is_file():
            return filename, path

    flat_path = settings.configs_dir / filename
    if flat_path.is_file():
        return filename, flat_path

    if isinstance(data, MutableMapping):
        kind = classify_config(data)
        if kind:
            return filename, resolve_config_path(settings.configs_dir, kind, filename)

    return filename, flat_path


def _parse_yaml_content(content: str):
    try:
        return yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"Invalid YAML: {exc}") from exc


def _refresh_connected_gantry_if_valid(filename: str, data: object) -> None:
    if not isinstance(data, MutableMapping):
        return
    try:
        config = GantryYamlSchema.model_validate(data)
    except ValidationError:
        return

    from zoo.routers import gantry as gantry_router

    session = gantry_router.current_session()
    if session is not None:
        session.refresh_connected_config(
            filename,
            config.model_dump(mode="json", exclude_none=True),
        )


@router.get("/{filename}")
def get_raw(filename: str) -> RawYaml:
    try:
        _, path = _resolve_raw_path(filename)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not path.is_file():
        raise HTTPException(404, f"Config not found: {filename}")
    return RawYaml(content=path.read_text())


@router.put("/{filename}")
def put_raw(filename: str, body: RawYaml) -> RawYaml:
    data = _parse_yaml_content(body.content)
    try:
        filename, path = _resolve_raw_path(filename, data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    atomic_write_text(path, body.content)
    _refresh_connected_gantry_if_valid(filename, data)
    return RawYaml(content=path.read_text())
