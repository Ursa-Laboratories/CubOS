"""Tests for protocol-layer measurement normalization."""

from __future__ import annotations

import pytest

from instruments.uvvis_ccs.models import UVVisSpectrum
from protocol_engine.measurements import (
    InstrumentMeasurement,
    MeasurementType,
    normalize_measurement,
)


def _make_uvvis_spectrum() -> UVVisSpectrum:
    return UVVisSpectrum(
        wavelengths=(400.0, 500.0, 600.0),
        intensities=(0.1, 0.2, 0.3),
        integration_time_s=0.24,
    )


class TestNormalizeMeasurement:

    def test_normalize_uvvis_returns_instrument_measurement(self):
        measurement = normalize_measurement(
            instrument_name="uvvis",
            method_name="measure",
            raw_result=_make_uvvis_spectrum(),
        )

        assert isinstance(measurement, InstrumentMeasurement)
        assert measurement.measurement_type == MeasurementType.UVVIS_SPECTRUM

    def test_normalize_uvvis_maps_mofcat_style_payload_fields(self):
        measurement = normalize_measurement(
            instrument_name="uvvis",
            method_name="measure",
            raw_result=_make_uvvis_spectrum(),
        )

        assert measurement.payload["wavelength_nm"] == [400.0, 500.0, 600.0]
        assert measurement.payload["intensity_au"] == [0.1, 0.2, 0.3]

    def test_normalize_uvvis_captures_integration_time_in_metadata(self):
        measurement = normalize_measurement(
            instrument_name="uvvis",
            method_name="measure",
            raw_result=_make_uvvis_spectrum(),
        )

        assert measurement.metadata["integration_time_s"] == pytest.approx(0.24)

    def test_unknown_measurement_type_raises_type_error(self):
        with pytest.raises(TypeError, match="Unsupported measurement result"):
            normalize_measurement(
                instrument_name="uvvis",
                method_name="measure",
                raw_result=object(),
            )

    def test_normalize_asmi_indentation_without_return_mode(self):
        raw_result = {
            "measurements": [
                {"z_mm": -73.01, "raw_force_n": 0.10, "corrected_force_n": 0.01},
                {"z_mm": -73.02, "raw_force_n": 0.11, "corrected_force_n": 0.02},
            ],
            "baseline_avg": 0.09,
            "baseline_std": 0.001,
            "force_exceeded": False,
            "data_points": 2,
        }

        measurement = normalize_measurement(
            instrument_name="asmi",
            method_name="indentation",
            raw_result=raw_result,
        )

        assert measurement.measurement_type == MeasurementType.ASMI_INDENTATION
        assert measurement.payload["z_positions_mm"] == [-73.01, -73.02]
        # Legacy untagged payloads default to "down" so the normalized
        # schema always exposes directions.
        assert measurement.payload["directions"] == ["down", "down"]
        assert measurement.metadata["measure_with_return"] is False

    def test_normalize_asmi_indentation_with_return_mode(self):
        raw_result = {
            "measurements": [
                {
                    "timestamp": 1761841220.199,
                    "z_mm": -73.01,
                    "raw_force_n": 0.10,
                    "corrected_force_n": 0.01,
                    "direction": "down",
                },
                {
                    "timestamp": 1761841220.327,
                    "z_mm": -73.02,
                    "raw_force_n": 0.11,
                    "corrected_force_n": 0.02,
                    "direction": "down",
                },
                {
                    "timestamp": 1761841220.453,
                    "z_mm": -73.01,
                    "raw_force_n": 0.09,
                    "corrected_force_n": 0.00,
                    "direction": "up",
                },
            ],
            "baseline_avg": 0.09,
            "baseline_std": 0.001,
            "force_exceeded": False,
            "data_points": 3,
            "measure_with_return": True,
        }

        measurement = normalize_measurement(
            instrument_name="asmi",
            method_name="indentation",
            raw_result=raw_result,
        )

        assert measurement.measurement_type == MeasurementType.ASMI_INDENTATION
        assert measurement.payload["timestamps_s"] == [
            1761841220.199,
            1761841220.327,
            1761841220.453,
        ]
        assert measurement.payload["directions"] == ["down", "down", "up"]
        assert measurement.metadata["measure_with_return"] is True

    def test_normalize_asmi_partial_direction_defaults_missing_to_down(self):
        """Mixed-tag step lists (one sample missing ``direction``) must default missing entries to 'down'."""
        raw_result = {
            "measurements": [
                {"z_mm": -73.01, "raw_force_n": 0.10, "corrected_force_n": 0.01, "direction": "down"},
                {"z_mm": -73.02, "raw_force_n": 0.11, "corrected_force_n": 0.02},
                {"z_mm": -73.01, "raw_force_n": 0.09, "corrected_force_n": 0.00, "direction": "up"},
            ],
            "baseline_avg": 0.09,
            "baseline_std": 0.001,
            "force_exceeded": False,
            "data_points": 3,
            "measure_with_return": True,
        }

        measurement = normalize_measurement(
            instrument_name="asmi",
            method_name="indentation",
            raw_result=raw_result,
        )

        assert measurement.payload["directions"] == ["down", "down", "up"]
