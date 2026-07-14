"""Tests for UV-Vis analysis helpers."""

from __future__ import annotations

import pytest

from cubos.data.analysis.uvvis import (
    UVVisRecord,
    load_uvvis_by_campaign,
    load_uvvis_by_experiment,
    peak_wavelength,
    absorbance,
    slice_wavelength_range,
)
from cubos.data.data_reader import DataReader
from cubos.data.data_store import DataStore
from cubos.protocol_engine.measurements import InstrumentMeasurement, MeasurementType


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _seed_uvvis_store() -> DataStore:
    store = DataStore(db_path=":memory:")
    cid = store.create_campaign(description="uvvis test")
    eid = store.create_experiment(cid, "plate_1", "A1", "[]")

    measurement = InstrumentMeasurement(
        measurement_type=MeasurementType.UVVIS_SPECTRUM,
        payload={
            "wavelength_nm": [400.0, 450.0, 500.0, 550.0, 600.0],
            "intensity_au": [0.1, 0.3, 0.8, 0.5, 0.2],
        },
        metadata={"integration_time_s": 0.24},
    )
    store.log_measurement(eid, measurement)
    return store


@pytest.fixture()
def seeded_reader() -> DataReader:
    store = _seed_uvvis_store()
    reader = DataReader(connection=store._conn)
    yield reader
    store.close()


# ─── Load from DB ────────────────────────────────────────────────────────────


class TestLoadUVVis:

    def test_load_by_experiment(self, seeded_reader: DataReader):
        spectra = load_uvvis_by_experiment(seeded_reader, experiment_id=1)
        assert len(spectra) == 1
        assert spectra[0].wavelengths == (400.0, 450.0, 500.0, 550.0, 600.0)
        assert spectra[0].intensities == (0.1, 0.3, 0.8, 0.5, 0.2)

    def test_load_by_campaign(self, seeded_reader: DataReader):
        spectra = load_uvvis_by_campaign(seeded_reader, campaign_id=1)
        assert len(spectra) == 1
        assert spectra[0].well_id == "A1"

    def test_load_empty(self, seeded_reader: DataReader):
        assert load_uvvis_by_experiment(seeded_reader, experiment_id=999) == []


# ─── Peak finding ────────────────────────────────────────────────────────────


class TestPeakWavelength:

    def test_finds_peak(self):
        record = UVVisRecord(
            measurement_id=1,
            experiment_id=1,
            wavelengths=(400.0, 450.0, 500.0, 550.0, 600.0),
            intensities=(0.1, 0.3, 0.8, 0.5, 0.2),
            integration_time_s=0.24,
        )
        wl, intensity = peak_wavelength(record)
        assert wl == 500.0
        assert intensity == 0.8

    def test_peak_with_single_point(self):
        record = UVVisRecord(
            measurement_id=1,
            experiment_id=1,
            wavelengths=(500.0,),
            intensities=(0.5,),
            integration_time_s=0.24,
        )
        wl, intensity = peak_wavelength(record)
        assert wl == 500.0

    def test_peak_empty_raises(self):
        record = UVVisRecord(
            measurement_id=1,
            experiment_id=1,
            wavelengths=(),
            intensities=(),
            integration_time_s=0.24,
        )
        with pytest.raises(ValueError, match="empty spectrum"):
            peak_wavelength(record)


# ─── Absorbance ──────────────────────────────────────────────────────────────


class TestAbsorbance:

    def test_computes_absorbance(self):
        sample = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0, 500.0),
            intensities=(50.0, 25.0),
            integration_time_s=0.24,
        )
        reference = UVVisRecord(
            measurement_id=2, experiment_id=1,
            wavelengths=(400.0, 500.0),
            intensities=(100.0, 100.0),
            integration_time_s=0.24,
        )
        result = absorbance(sample, reference)
        # A = -log10(sample / reference)
        # A(400) = -log10(50/100) = -log10(0.5) ≈ 0.301
        # A(500) = -log10(25/100) = -log10(0.25) ≈ 0.602
        assert result.wavelengths == (400.0, 500.0)
        assert result.intensities[0] == pytest.approx(0.30103, rel=1e-3)
        assert result.intensities[1] == pytest.approx(0.60206, rel=1e-3)

    def test_absorbance_with_dark(self):
        sample = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(60.0,),
            integration_time_s=0.24,
        )
        reference = UVVisRecord(
            measurement_id=2, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(110.0,),
            integration_time_s=0.24,
        )
        dark = UVVisRecord(
            measurement_id=3, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(10.0,),
            integration_time_s=0.24,
        )
        result = absorbance(sample, reference, dark=dark)
        # A = -log10((60-10) / (110-10)) = -log10(50/100) = 0.301
        assert result.intensities[0] == pytest.approx(0.30103, rel=1e-3)

    def test_absorbance_mismatched_lengths_raises(self):
        sample = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0, 500.0),
            intensities=(50.0, 25.0),
            integration_time_s=0.24,
        )
        reference = UVVisRecord(
            measurement_id=2, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(100.0,),
            integration_time_s=0.24,
        )
        with pytest.raises(ValueError, match="same length"):
            absorbance(sample, reference)

    def test_absorbance_mismatched_dark_length_raises(self):
        sample = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0, 500.0),
            intensities=(50.0, 25.0),
            integration_time_s=0.24,
        )
        reference = UVVisRecord(
            measurement_id=2, experiment_id=1,
            wavelengths=(400.0, 500.0),
            intensities=(100.0, 100.0),
            integration_time_s=0.24,
        )
        dark = UVVisRecord(
            measurement_id=3, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(10.0,),
            integration_time_s=0.24,
        )
        with pytest.raises(ValueError, match="same length"):
            absorbance(sample, reference, dark=dark)

    def test_absorbance_reference_equals_dark_raises(self):
        sample = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(50.0,),
            integration_time_s=0.24,
        )
        reference = UVVisRecord(
            measurement_id=2, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(10.0,),
            integration_time_s=0.24,
        )
        dark = UVVisRecord(
            measurement_id=3, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(10.0,),  # same as reference → division by zero
            integration_time_s=0.24,
        )
        with pytest.raises(ValueError, match="division by zero"):
            absorbance(sample, reference, dark=dark)

    def test_absorbance_non_positive_ratio_raises(self):
        # sample below dark → ratio < 0
        sample = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(5.0,),
            integration_time_s=0.24,
        )
        reference = UVVisRecord(
            measurement_id=2, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(100.0,),
            integration_time_s=0.24,
        )
        dark = UVVisRecord(
            measurement_id=3, experiment_id=1,
            wavelengths=(400.0,),
            intensities=(20.0,),  # dark > sample → negative ratio
            integration_time_s=0.24,
        )
        with pytest.raises(ValueError, match="Non-positive signal ratio"):
            absorbance(sample, reference, dark=dark)


# ─── Wavelength slicing ──────────────────────────────────────────────────────


class TestSliceWavelengthRange:

    def test_slices_range(self):
        record = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0, 450.0, 500.0, 550.0, 600.0),
            intensities=(0.1, 0.3, 0.8, 0.5, 0.2),
            integration_time_s=0.24,
        )
        sliced = slice_wavelength_range(record, wl_min=450.0, wl_max=550.0)
        assert sliced.wavelengths == (450.0, 500.0, 550.0)
        assert sliced.intensities == (0.3, 0.8, 0.5)

    def test_slice_preserves_metadata(self):
        record = UVVisRecord(
            measurement_id=7, experiment_id=3,
            wavelengths=(400.0, 500.0, 600.0),
            intensities=(0.1, 0.5, 0.3),
            integration_time_s=1.5,
            well_id="B2",
        )
        sliced = slice_wavelength_range(record, wl_min=400.0, wl_max=500.0)
        assert sliced.measurement_id == 7
        assert sliced.experiment_id == 3
        assert sliced.integration_time_s == 1.5
        assert sliced.well_id == "B2"

    def test_slice_empty_range(self):
        record = UVVisRecord(
            measurement_id=1, experiment_id=1,
            wavelengths=(400.0, 500.0, 600.0),
            intensities=(0.1, 0.5, 0.3),
            integration_time_s=0.24,
        )
        sliced = slice_wavelength_range(record, wl_min=700.0, wl_max=800.0)
        assert sliced.wavelengths == ()
        assert sliced.intensities == ()
