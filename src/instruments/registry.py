"""Instrument registry: supported types, vendors, and extension loading."""

from __future__ import annotations

import copy
import inspect
import importlib
import os
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Type

import yaml

from instruments.base_instrument import BaseInstrument

_REGISTRY_PATH = Path(__file__).parent / "registry.yaml"
_ENTRY_POINT_GROUP = "cubos.instrument_registries"
_OVERLAY_ENV_VAR = "CUBOS_INSTRUMENT_REGISTRY_PATHS"
_VALID_CALIBRATION_MODES = {"contact", "non_contact"}

_cache: Dict[str, Any] | None = None


def load_registry() -> Dict[str, Any]:
    """Load built-in and external instrument registry definitions.

    Merge order is:
    1. CubOS built-in ``registry.yaml``.
    2. Installed package entry points in ``cubos.instrument_registries``.
    3. Explicit overlay YAML paths from ``CUBOS_INSTRUMENT_REGISTRY_PATHS``.

    Entry points may return a registry mapping, a path to a registry YAML file,
    or a callable returning either of those. Overlay paths use ``os.pathsep`` as
    the separator, so ``:`` on POSIX and ``;`` on Windows.
    """
    global _cache
    if _cache is None:
        registry = _load_registry_file(_REGISTRY_PATH)
        for source, overlay in _entry_point_registries():
            _merge_registry(registry, overlay, source=source)
        for path in _overlay_paths():
            _merge_registry(
                registry,
                _load_registry_file(path),
                source=f"overlay {path}",
            )
        _validate_registry(registry)
        _cache = registry
    return copy.deepcopy(_cache)


def get_supported_types() -> list[str]:
    """Return a sorted list of all supported instrument type keys."""
    return sorted(load_registry()["instruments"].keys())


def get_supported_vendors(instrument_type: str) -> list[str]:
    """Return allowed vendors for an instrument type."""
    entry = _instrument_entry(instrument_type)
    return sorted(entry["vendors"].keys())


def get_calibration_mode(instrument_type: str) -> str:
    """Return calibration mode for an instrument type.

    ``contact`` instruments touch the shared calibration block. ``non_contact``
    instruments are centered over the block and calibrated from a measured
    distance above the block top.
    """
    entry = _instrument_entry(instrument_type)
    return entry.get("calibration_mode", "contact")


def get_instrument_interface(instrument_type: str) -> Type[BaseInstrument]:
    """Import and return the generic interface class for an instrument type."""
    entry = _instrument_entry(instrument_type)
    module_path, class_name = entry["interface"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    if not issubclass(cls, BaseInstrument):
        raise TypeError(
            f"Interface {entry['interface']} for '{instrument_type}' is not "
            "a BaseInstrument subclass."
        )
    return cls


def get_instrument_class(
    instrument_type: str,
    vendor: str,
) -> Type[BaseInstrument]:
    """Import and return the concrete driver class for a type/vendor pair."""
    vendor_entry = _vendor_entry(instrument_type, vendor)
    module = importlib.import_module(vendor_entry["module"])
    cls = getattr(module, vendor_entry["class_name"])
    if not issubclass(cls, get_instrument_interface(instrument_type)):
        raise TypeError(
            f"Driver {vendor_entry['module']}.{vendor_entry['class_name']} "
            f"for '{instrument_type}/{vendor}' does not implement "
            f"{get_instrument_interface(instrument_type).__name__}."
        )
    if inspect.isabstract(cls):
        missing_methods = sorted(getattr(cls, "__abstractmethods__", set()))
        raise TypeError(
            f"Driver {vendor_entry['module']}.{vendor_entry['class_name']} "
            f"for '{instrument_type}/{vendor}' is missing required interface "
            f"methods: {missing_methods}."
        )
    return cls


def validate_instrument(instrument_type: str, vendor: str) -> None:
    """Validate that a type+vendor combination is supported."""
    _vendor_entry(instrument_type, vendor)


def _instrument_entry(instrument_type: str) -> dict[str, Any]:
    instruments = load_registry()["instruments"]
    if instrument_type not in instruments:
        raise ValueError(
            f"Unknown instrument type '{instrument_type}'. "
            f"Supported types: {sorted(instruments.keys())}"
        )
    return instruments[instrument_type]


def _vendor_entry(instrument_type: str, vendor: str) -> dict[str, Any]:
    entry = _instrument_entry(instrument_type)
    vendors = entry["vendors"]
    if vendor not in vendors:
        raise ValueError(
            f"'{vendor}' is not a supported vendor for '{instrument_type}'. "
            f"Allowed vendors: {sorted(vendors.keys())}"
        )
    return vendors[vendor]


def _load_registry_file(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    with resolved.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Instrument registry {resolved} must be a mapping.")
    if "instruments" not in loaded:
        raise ValueError(
            f"Instrument registry {resolved} must define an 'instruments' mapping."
        )
    return copy.deepcopy(loaded)


def _entry_point_registries() -> Iterable[tuple[str, dict[str, Any]]]:
    try:
        entry_points = importlib_metadata.entry_points()
    except Exception:
        return []

    if hasattr(entry_points, "select"):
        selected = entry_points.select(group=_ENTRY_POINT_GROUP)
    elif isinstance(entry_points, dict):  # pragma: no cover - older API
        selected = entry_points.get(_ENTRY_POINT_GROUP, [])
    else:  # pragma: no cover - defensive for test doubles / unusual APIs
        selected = []

    overlays: list[tuple[str, dict[str, Any]]] = []
    for entry_point in selected:
        source = f"entry point {entry_point.name}"
        loaded = entry_point.load()
        overlays.append((source, _registry_from_external_source(loaded, source)))
    return overlays


def _registry_from_external_source(source_obj: Any, source: str) -> dict[str, Any]:
    if callable(source_obj) and not isinstance(source_obj, (str, Path, Mapping)):
        source_obj = source_obj()
    if isinstance(source_obj, (str, Path)):
        return _load_registry_file(source_obj)
    if isinstance(source_obj, Mapping):
        registry = copy.deepcopy(dict(source_obj))
        if "instruments" not in registry:
            raise ValueError(f"Instrument registry from {source} is missing instruments.")
        return registry
    raise TypeError(
        f"Instrument registry {source} must load to a mapping, path, or callable."
    )


def _overlay_paths() -> list[Path]:
    raw = os.environ.get(_OVERLAY_ENV_VAR, "")
    if not raw.strip():
        return []
    return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]


def _merge_registry(
    base: dict[str, Any],
    incoming: Mapping[str, Any],
    *,
    source: str,
) -> None:
    base_instruments = base.setdefault("instruments", {})
    incoming_instruments = incoming.get("instruments")
    if not isinstance(incoming_instruments, Mapping):
        raise ValueError(f"Instrument registry {source} must define instruments.")

    for type_key, raw_entry in incoming_instruments.items():
        if not isinstance(raw_entry, Mapping):
            raise ValueError(f"Instrument entry {type_key!r} from {source} must map.")
        entry = copy.deepcopy(dict(raw_entry))
        type_override = bool(entry.pop("override", False))
        vendors = copy.deepcopy(dict(entry.pop("vendors", {}) or {}))
        if not isinstance(vendors, dict):
            raise ValueError(
                f"Instrument entry {type_key!r} from {source} has invalid vendors."
            )

        if type_key not in base_instruments:
            entry["vendors"] = _clean_vendor_entries(type_key, vendors, source)
            base_instruments[type_key] = entry
            continue

        existing = base_instruments[type_key]
        for key, value in entry.items():
            if key not in existing or existing[key] == value:
                existing[key] = value
                continue
            if not type_override:
                raise ValueError(
                    f"Instrument type '{type_key}' from {source} attempts to "
                    f"change '{key}'. Add override: true to the type entry if "
                    "this is intentional."
                )
            existing[key] = value

        existing_vendors = existing.setdefault("vendors", {})
        for vendor_key, vendor_entry in _clean_vendor_entries(
            type_key, vendors, source,
        ).items():
            vendor_override = bool(vendor_entry.pop("override", False))
            if vendor_key in existing_vendors and not vendor_override:
                raise ValueError(
                    f"Vendor '{vendor_key}' for instrument type '{type_key}' "
                    f"is already registered. Add override: true to the vendor "
                    f"entry in {source} if this replacement is intentional."
                )
            existing_vendors[vendor_key] = vendor_entry


def _clean_vendor_entries(
    type_key: str,
    vendors: Mapping[str, Any],
    source: str,
) -> dict[str, dict[str, Any]]:
    cleaned: dict[str, dict[str, Any]] = {}
    for vendor_key, raw_vendor in vendors.items():
        if not isinstance(raw_vendor, Mapping):
            raise ValueError(
                f"Vendor entry '{type_key}/{vendor_key}' from {source} must map."
            )
        cleaned[vendor_key] = copy.deepcopy(dict(raw_vendor))
    return cleaned


def _validate_registry(registry: Mapping[str, Any]) -> None:
    instruments = registry.get("instruments")
    if not isinstance(instruments, Mapping) or not instruments:
        raise ValueError("Instrument registry must define at least one instrument.")
    for type_key, entry in instruments.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"Instrument entry '{type_key}' must be a mapping.")
        if not isinstance(entry.get("interface"), str) or "." not in entry["interface"]:
            raise ValueError(
                f"Instrument entry '{type_key}' must define a dotted interface."
            )
        mode = entry.get("calibration_mode", "contact")
        if mode not in _VALID_CALIBRATION_MODES:
            raise ValueError(
                f"Instrument entry '{type_key}' has invalid calibration_mode "
                f"{mode!r}; expected one of {sorted(_VALID_CALIBRATION_MODES)}."
            )
        vendors = entry.get("vendors")
        if not isinstance(vendors, Mapping) or not vendors:
            raise ValueError(
                f"Instrument entry '{type_key}' must define at least one vendor."
            )
        for vendor_key, vendor_entry in vendors.items():
            if not isinstance(vendor_entry, Mapping):
                raise ValueError(
                    f"Vendor entry '{type_key}/{vendor_key}' must be a mapping."
                )
            for required in ("module", "class_name"):
                if not isinstance(vendor_entry.get(required), str):
                    raise ValueError(
                        f"Vendor entry '{type_key}/{vendor_key}' must define "
                        f"{required}."
                    )
