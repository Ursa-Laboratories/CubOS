"""Protocol-layer measurement normalization and typing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from instruments.uvvis_ccs.models import UVVisSpectrum

# Potentiostat results are recognised by duck-typing on their `.technique`
# attribute (see `_POTENTIOSTAT_TECHNIQUES` below). Concrete classes are
# NOT imported here so protocol_engine stays decoupled from the
# instrument packages.


class MeasurementType(str, Enum):
    """Normalized measurement types understood by protocol persistence."""

    UVVIS_SPECTRUM = "uvvis_spectrum"
    ASMI_INDENTATION = "asmi_indentation"
    POTENTIOSTAT_OCP = "potentiostat_ocp"
    POTENTIOSTAT_CA = "potentiostat_ca"
    POTENTIOSTAT_CV = "potentiostat_cv"
    POTENTIOSTAT_CP = "potentiostat_cp"


@dataclass(frozen=True)
class InstrumentMeasurement:
    """Instrument-agnostic measurement returned by protocol normalization."""

    measurement_type: MeasurementType
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


_POTENTIOSTAT_TECHNIQUES = {
    "ocp": MeasurementType.POTENTIOSTAT_OCP,
    "ca": MeasurementType.POTENTIOSTAT_CA,
    "cp": MeasurementType.POTENTIOSTAT_CP,
    "cv": MeasurementType.POTENTIOSTAT_CV,
}


def _is_potentiostat_result(raw_result: Any) -> bool:
    """True if ``raw_result`` quacks like an ``instruments.potentiostat`` result."""
    technique = getattr(raw_result, "technique", None)
    if technique not in _POTENTIOSTAT_TECHNIQUES:
        return False
    for attr in ("time_s", "voltage_v", "vendor", "metadata"):
        if not hasattr(raw_result, attr):
            return False
    return True


def _potentiostat_base_metadata(
    raw_result: Any,
    instrument_name: str,
    method_name: str,
) -> dict[str, Any]:
    """Common metadata keys for every potentiostat result type."""
    return {
        **dict(raw_result.metadata),
        "technique": raw_result.technique,
        "vendor": raw_result.vendor,
        "instrument_name": instrument_name,
        "method_name": method_name,
    }


def _normalize_potentiostat_result(
    raw_result: Any,
    instrument_name: str,
    method_name: str,
) -> "InstrumentMeasurement":
    """Build an ``InstrumentMeasurement`` from a potentiostat result via duck-typing.

    Per-technique scalar fields are optional — only OCP lacks ``current_a`` —
    so we probe each expected attribute with ``getattr`` and skip missing ones.
    """
    technique = raw_result.technique
    measurement_type = _POTENTIOSTAT_TECHNIQUES[technique]
    meta = _potentiostat_base_metadata(raw_result, instrument_name, method_name)

    payload: dict[str, Any] = {
        "time_s": list(raw_result.time_s),
        "voltage_v": list(raw_result.voltage_v),
    }
    if hasattr(raw_result, "current_a"):
        payload["current_a"] = list(raw_result.current_a)

    for attr in (
        "sample_period_s",
        "duration_s",
        "step_potential_v",
        "step_current_a",
        "scan_rate_v_s",
        "step_size_v",
        "cycles",
    ):
        if hasattr(raw_result, attr):
            meta[attr] = getattr(raw_result, attr)

    return InstrumentMeasurement(
        measurement_type=measurement_type,
        payload=payload,
        metadata=meta,
    )


def normalize_measurement(
    instrument_name: str,
    method_name: str,
    raw_result: Any,
) -> InstrumentMeasurement:
    """Normalize a raw instrument result into a protocol measurement object."""
    if isinstance(raw_result, UVVisSpectrum):
        return InstrumentMeasurement(
            measurement_type=MeasurementType.UVVIS_SPECTRUM,
            payload={
                # Align field names with mofcat-workflow conventions.
                "wavelength_nm": list(raw_result.wavelengths),
                "intensity_au": list(raw_result.intensities),
            },
            metadata={
                "integration_time_s": raw_result.integration_time_s,
                "instrument_name": instrument_name,
                "method_name": method_name,
            },
        )

    if isinstance(raw_result, dict) and "measurements" in raw_result:
        steps = raw_result["measurements"]
        payload = {
            "sample_timestamps": [s["timestamp"] for s in steps],
            "z_positions_mm": [s["z_mm"] for s in steps],
            "raw_forces_n": [s["raw_force_n"] for s in steps],
            "corrected_forces_n": [s["corrected_force_n"] for s in steps],
            "directions": [s["direction"] for s in steps],
        }
        return InstrumentMeasurement(
            measurement_type=MeasurementType.ASMI_INDENTATION,
            payload=payload,
            metadata={
                "baseline_avg": raw_result.get("baseline_avg", 0.0),
                "baseline_std": raw_result.get("baseline_std", 0.0),
                "force_exceeded": raw_result.get("force_exceeded", False),
                "data_points": raw_result.get("data_points", len(steps)),
                "measure_with_return": raw_result.get("measure_with_return", False),
                "step_size_mm": raw_result.get("step_size_mm"),
                "z_target_mm": raw_result.get("z_target_mm"),
                "force_limit_n": raw_result.get("force_limit_n"),
                "instrument_name": instrument_name,
                "method_name": method_name,
            },
        )

    if _is_potentiostat_result(raw_result):
        return _normalize_potentiostat_result(
            raw_result, instrument_name, method_name,
        )

    raise TypeError(
        "Unsupported measurement result type: "
        f"{type(raw_result).__name__} from {instrument_name}.{method_name}"
    )
