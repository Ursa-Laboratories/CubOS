"""Unit tests for potentiostat params/results dataclasses and exceptions."""

import pytest

from cubos.instruments.base_instrument import InstrumentError
from cubos.instruments.potentiostat.exceptions import (
    PotentiostatCommandError,
    PotentiostatConfigError,
    PotentiostatConnectionError,
    PotentiostatError,
    PotentiostatTimeoutError,
)
from cubos.instruments.potentiostat.models import (
    CAParams,
    CAResult,
    CPParams,
    CPResult,
    CVParams,
    CVResult,
    OCPParams,
    OCPResult,
)


# --- Exception hierarchy ------------------------------------------------------


class TestExceptionHierarchy:

    @pytest.mark.parametrize(
        "cls",
        [
            PotentiostatConnectionError,
            PotentiostatCommandError,
            PotentiostatTimeoutError,
            PotentiostatConfigError,
        ],
    )
    def test_subclasses_inherit_from_potentiostat_error(self, cls):
        assert issubclass(cls, PotentiostatError)

    def test_potentiostat_error_inherits_from_instrument_error(self):
        assert issubclass(PotentiostatError, InstrumentError)


# --- CVParams -----------------------------------------------------------------


class TestCVParams:

    def test_valid_params_construct(self):
        p = CVParams(
            start_V=0.0,
            vertex1_V=0.5,
            vertex2_V=-0.5,
            end_V=0.0,
            scan_rate_V_per_s=0.05,
            cycles=3,
            sampling_interval_s=0.02,
        )
        assert p.cycles == 3
        assert p.scan_rate_V_per_s == 0.05

    def test_frozen(self):
        p = CVParams(0.0, 0.5, -0.5, 0.0, 0.05)
        with pytest.raises(AttributeError):
            p.cycles = 5  # type: ignore[misc]

    def test_zero_scan_rate_rejected(self):
        with pytest.raises(PotentiostatConfigError, match="scan_rate_V_per_s"):
            CVParams(0.0, 0.5, -0.5, 0.0, 0.0)

    def test_negative_scan_rate_rejected(self):
        with pytest.raises(PotentiostatConfigError):
            CVParams(0.0, 0.5, -0.5, 0.0, -0.1)

    def test_zero_cycles_rejected(self):
        with pytest.raises(PotentiostatConfigError, match="cycles"):
            CVParams(0.0, 0.5, -0.5, 0.0, 0.05, cycles=0)

    def test_zero_sampling_interval_rejected(self):
        with pytest.raises(PotentiostatConfigError, match="sampling_interval_s"):
            CVParams(0.0, 0.5, -0.5, 0.0, 0.05, sampling_interval_s=0.0)

    def test_identical_vertices_rejected(self):
        with pytest.raises(PotentiostatConfigError, match="vertex"):
            CVParams(0.0, 0.5, 0.5, 0.0, 0.05)


# --- OCPParams / CAParams / CPParams -----------------------------------------


class TestDurationParams:

    @pytest.mark.parametrize(
        "cls,kwargs",
        [
            (OCPParams, {"duration_s": 10.0}),
            (CAParams, {"potential_V": 0.5, "duration_s": 10.0}),
            (CPParams, {"current_A": 1e-3, "duration_s": 10.0}),
        ],
    )
    def test_valid(self, cls, kwargs):
        p = cls(**kwargs)
        assert p.duration_s == 10.0

    @pytest.mark.parametrize(
        "cls,kwargs",
        [
            (OCPParams, {"duration_s": 0.0}),
            (CAParams, {"potential_V": 0.5, "duration_s": 0.0}),
            (CPParams, {"current_A": 1e-3, "duration_s": 0.0}),
        ],
    )
    def test_zero_duration_rejected(self, cls, kwargs):
        with pytest.raises(PotentiostatConfigError, match="duration_s"):
            cls(**kwargs)

    @pytest.mark.parametrize(
        "cls,kwargs",
        [
            (OCPParams, {"duration_s": 1.0, "sampling_interval_s": 0.0}),
            (CAParams, {"potential_V": 0.5, "duration_s": 1.0, "sampling_interval_s": 0.0}),
            (CPParams, {"current_A": 1e-3, "duration_s": 1.0, "sampling_interval_s": 0.0}),
        ],
    )
    def test_zero_sampling_interval_rejected(self, cls, kwargs):
        with pytest.raises(PotentiostatConfigError, match="sampling_interval_s"):
            cls(**kwargs)

    def test_sampling_interval_larger_than_duration_rejected(self):
        with pytest.raises(PotentiostatConfigError, match="sampling_interval_s"):
            OCPParams(duration_s=0.5, sampling_interval_s=1.0)


# --- Result dataclasses -------------------------------------------------------


class TestOCPResult:

    def test_fields_and_technique(self):
        r = OCPResult(
            time_s=(0.0, 0.1, 0.2),
            voltage_v=(0.35, 0.36, 0.37),
            sample_period_s=0.1,
            duration_s=0.3,
            vendor="admiral",
        )
        assert r.technique == "ocp"
        assert r.final_voltage_v == 0.37
        assert r.is_valid
        assert r.metadata == {}

    def test_empty_trace_not_valid(self):
        r = OCPResult(
            time_s=(),
            voltage_v=(),
            sample_period_s=0.1,
            duration_s=1.0,
            vendor="admiral",
        )
        assert r.final_voltage_v is None
        assert not r.is_valid

    def test_frozen(self):
        r = OCPResult(
            time_s=(0.0,), voltage_v=(0.5,),
            sample_period_s=0.1, duration_s=1.0, vendor="admiral",
        )
        with pytest.raises(AttributeError):
            r.duration_s = 9.9  # type: ignore[misc]


class TestCAResult:

    def test_fields_and_technique(self):
        r = CAResult(
            time_s=(0.0, 0.01),
            voltage_v=(0.5, 0.5),
            current_a=(1e-6, 9e-7),
            sample_period_s=0.01,
            duration_s=0.02,
            step_potential_v=0.5,
            vendor="admiral",
        )
        assert r.technique == "ca"
        assert r.is_valid

    def test_mismatched_lengths_not_valid(self):
        r = CAResult(
            time_s=(0.0, 0.01),
            voltage_v=(0.5,),
            current_a=(1e-6,),
            sample_period_s=0.01,
            duration_s=0.02,
            step_potential_v=0.5,
            vendor="admiral",
        )
        assert not r.is_valid


class TestCPResult:

    def test_fields_and_technique(self):
        r = CPResult(
            time_s=(0.0, 0.01),
            voltage_v=(0.1, 0.11),
            current_a=(1e-3, 1e-3),
            sample_period_s=0.01,
            duration_s=0.02,
            step_current_a=1e-3,
            vendor="admiral",
        )
        assert r.technique == "cp"
        assert r.is_valid
        assert r.step_current_a == 1e-3


class TestCVResult:

    def test_fields_and_technique(self):
        r = CVResult(
            time_s=(0.0, 0.01, 0.02),
            voltage_v=(0.0, 0.1, 0.2),
            current_a=(1e-6, 2e-6, 3e-6),
            scan_rate_v_s=0.05,
            step_size_v=0.0005,
            cycles=2,
            vendor="admiral",
            metadata={"device_id": "abc"},
        )
        assert r.technique == "cv"
        assert r.is_valid
        assert r.cycles == 2
        assert r.metadata["device_id"] == "abc"

    def test_zero_cycles_not_valid(self):
        r = CVResult(
            time_s=(0.0,), voltage_v=(0.0,), current_a=(1e-6,),
            scan_rate_v_s=0.05, step_size_v=0.0005, cycles=0,
            vendor="admiral",
        )
        assert not r.is_valid

    def test_frozen(self):
        r = CVResult(
            time_s=(0.0,), voltage_v=(0.0,), current_a=(1e-6,),
            scan_rate_v_s=0.05, step_size_v=0.0005, cycles=1,
            vendor="admiral",
        )
        with pytest.raises(AttributeError):
            r.cycles = 9  # type: ignore[misc]
