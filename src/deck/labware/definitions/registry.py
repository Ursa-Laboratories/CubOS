"""Labware definition registry: single source of truth for supported
definitions, their backing Labware class, and a per-folder config YAML
mapping each attribute onto the class fields.

Mirrors the design of :mod:`instruments.registry`: a tiny module-level
cache around ``registry.yaml``, plus helpers to resolve the class and
config for a definition name.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict, List, Type

from yaml_utils import load_yaml_file

from ..labware import Labware

_DEFINITIONS_DIR = Path(__file__).parent
_REGISTRY_PATH = _DEFINITIONS_DIR / "registry.yaml"

_cache: Dict[str, Any] | None = None


def load_registry() -> Dict[str, Any]:
    """Load and cache the labware registry from ``registry.yaml``."""
    global _cache
    if _cache is None:
        _cache = load_yaml_file(_REGISTRY_PATH) or {}
    return _cache


def _labware_entries() -> Dict[str, Dict[str, Any]]:
    entries = load_registry().get("labware") or {}
    if not isinstance(entries, dict):
        raise ValueError(
            f"registry.yaml must have a top-level `labware:` mapping, got {type(entries).__name__}"
        )
    return entries


def get_supported_definitions() -> List[str]:
    """Return a sorted list of all supported labware definition names."""
    return sorted(_labware_entries().keys())


def _require_entry(definition: str) -> Dict[str, Any]:
    entries = _labware_entries()
    if definition not in entries:
        raise ValueError(
            f"Unknown labware definition '{definition}'. "
            f"Supported definitions: {sorted(entries.keys())}"
        )
    return entries[definition]


def get_labware_class(definition: str) -> Type[Labware]:
    """Dynamically import and return the Labware subclass for a definition."""
    entry = _require_entry(definition)
    module = importlib.import_module(entry["module"])
    return getattr(module, entry["class_name"])


def load_definition_config(definition: str) -> Dict[str, Any]:
    """Load a definition's config YAML as a flat attribute dict.

    The returned mapping is the exact set of keyword arguments that should
    be passed to the labware class constructor, minus ``location`` (which
    is supplied per-instance at the deck layer).
    """
    entry = _require_entry(definition)
    config_path = _DEFINITIONS_DIR / entry["config"]
    data = load_yaml_file(config_path) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Config file '{config_path}' must be a YAML mapping; got {type(data).__name__}."
        )
    return data


def build_labware(definition: str, **overrides: Any) -> Labware:
    """Instantiate a Labware from its definition, applying any keyword overrides.

    Typical usage from a deck loader::

        from deck.labware.definitions.registry import build_labware
        from deck.labware.labware import Coordinate3D

        holder = build_labware(
            "ursa_vial_holder",
            location=Coordinate3D(x=17.1, y=132.9, z=164.0),
        )

    Fields present in ``overrides`` win over fields from the config YAML,
    which in turn win over Python class defaults.
    """
    cls = get_labware_class(definition)
    kwargs = {**load_definition_config(definition), **overrides}
    return cls(**kwargs)


def _reset_cache() -> None:
    """Testing helper — forget the cached registry."""
    global _cache
    _cache = None
