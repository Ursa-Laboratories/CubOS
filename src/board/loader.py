"""Load runtime Board objects from gantry machine config or legacy board YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, TYPE_CHECKING

import yaml
from pydantic import ValidationError

from instruments.base_instrument import BaseInstrument
from instruments.registry import get_instrument_class, validate_instrument
from gantry.grbl_settings import normalize_expected_grbl_settings

from .board import Board
from .errors import BoardLoaderError
from .yaml_schema import BoardYamlSchema

if TYPE_CHECKING:
    from gantry import Gantry


def _format_loader_exception(path: Path, error: Exception) -> str:
    """Return a concise, actionable error message."""
    detail = str(error)

    if isinstance(error, ValidationError):
        first = error.errors()[0] if error.errors() else {}
        detail = first.get("msg", detail)
        location = ".".join(str(part) for part in first.get("loc", []))
        error_type = first.get("type", "")

        if "missing" in error_type or "Field required" in detail:
            guidance = "Add the missing required YAML field shown in the error location."
        elif "extra_forbidden" in error_type or "Extra inputs are not permitted" in detail:
            guidance = "Remove unknown YAML fields; only 'instruments' and 'grbl_settings' are allowed at root."
        else:
            guidance = "Review the YAML values against the board schema."

        prefix = f" at `{location}`" if location else ""
        return f"Board YAML error{prefix}: {detail}\nHow to fix: {guidance}"

    if isinstance(error, yaml.YAMLError):
        return (
            f"Board YAML parse error in `{path}`.\n"
            "How to fix: Check YAML indentation, colons, and structure."
        )

    if isinstance(error, ValueError):
        if "must define mounted instruments" in detail:
            return (
                f"Machine config error in `{path}`: {detail}\n"
                "How to fix: Add a top-level 'instruments' section to the gantry YAML."
            )
        return (
            f"Instrument validation error in `{path}`: {detail}\n"
            f"How to fix: Check type and vendor against the instrument registry."
        )

    return (
        f"Board loader error in `{path}`: {detail}\n"
        "How to fix: Verify the file path and board YAML contents."
    )


def _instantiate_instruments(
    instrument_configs: Mapping[str, Mapping[str, Any]],
    *,
    mock_mode: bool = False,
) -> Dict[str, BaseInstrument]:
    instruments: Dict[str, BaseInstrument] = {}
    for name, entry in instrument_configs.items():
        kwargs = dict(entry)
        type_key = kwargs.pop("type")
        vendor = kwargs.pop("vendor")
        validate_instrument(type_key, vendor)
        if mock_mode:
            kwargs["offline"] = True
        cls = get_instrument_class(type_key)
        instruments[name] = cls(**kwargs)
    return instruments


def build_board_from_instrument_configs(
    instrument_configs: Mapping[str, Mapping[str, Any]],
    gantry: Gantry,
    *,
    expected_grbl_settings: dict[str, float] | None = None,
    mock_mode: bool = False,
    safe_z: float | None = None,
) -> Board:
    """Build a Board from parsed instrument config entries."""
    return Board(
        gantry=gantry,
        instruments=_instantiate_instruments(
            instrument_configs,
            mock_mode=mock_mode,
        ),
        expected_grbl_settings=expected_grbl_settings,
        safe_z=safe_z,
    )


def load_board_from_gantry_config(
    config: Any,
    gantry: Gantry,
    mock_mode: bool = False,
) -> Board:
    """Load the runtime Board from a loaded gantry machine config."""
    instrument_configs = getattr(config, "instruments", None)
    if not instrument_configs:
        raise ValueError(
            "Gantry machine config must define mounted instruments under "
            "the top-level 'instruments' key."
        )
    expected_grbl_settings = getattr(config, "expected_grbl_settings", None)
    safe_z = getattr(config, "resolved_safe_z", None)
    return build_board_from_instrument_configs(
        instrument_configs,
        gantry,
        expected_grbl_settings=expected_grbl_settings,
        mock_mode=mock_mode,
        safe_z=safe_z,
    )


def load_board_from_gantry_yaml(
    path: str | Path,
    gantry: Gantry,
    mock_mode: bool = False,
) -> Board:
    """Load a Board from the instruments embedded in a gantry YAML file."""
    from gantry.loader import load_gantry_from_yaml

    config = load_gantry_from_yaml(path)
    return load_board_from_gantry_config(
        config,
        gantry,
        mock_mode=mock_mode,
    )


def load_board_from_gantry_yaml_safe(
    path: str | Path,
    gantry: Gantry,
    mock_mode: bool = False,
) -> Board:
    """Load board-from-gantry YAML with user-friendly exception formatting."""
    resolved = Path(path)
    try:
        return load_board_from_gantry_yaml(resolved, gantry, mock_mode=mock_mode)
    except Exception as exc:
        raise BoardLoaderError(_format_loader_exception(resolved, exc)) from exc


def load_board_from_yaml(
    path: str | Path, gantry: Gantry, mock_mode: bool = False,
) -> Board:
    """Load a legacy board YAML file and return a Board with instruments.

    Args:
        path: Path to the board YAML file.
        gantry: The Gantry instance to attach to the Board.
        mock_mode: If True, all instruments are created with offline=True.

    Returns:
        Board with all instruments instantiated from the YAML config.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
        ValidationError: If the YAML does not match the schema.
        ValueError: If an instrument type or vendor is invalid.
    """
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raw = {}

    schema = BoardYamlSchema.model_validate(raw)

    return build_board_from_instrument_configs(
        {
            name: entry.model_dump()
            for name, entry in schema.instruments.items()
        },
        gantry=gantry,
        expected_grbl_settings=normalize_expected_grbl_settings(schema.grbl_settings),
        mock_mode=mock_mode,
    )


def load_board_from_yaml_safe(
    path: str | Path, gantry: Gantry, mock_mode: bool = False,
) -> Board:
    """Load board YAML with user-friendly exception formatting."""
    resolved = Path(path)
    try:
        return load_board_from_yaml(resolved, gantry, mock_mode=mock_mode)
    except Exception as exc:
        raise BoardLoaderError(_format_loader_exception(resolved, exc)) from exc
