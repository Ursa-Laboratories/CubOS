"""Unit tests for :mod:`protocol_engine.scan_args`."""

from __future__ import annotations

import pytest

from protocol_engine.scan_args import (
    NormalizedScanArguments,
    normalize_scan_arguments,
)


class TestNormalizeScanArguments:

    def test_returns_empty_method_kwargs_when_nothing_passed(self):
        normalized = normalize_scan_arguments()
        assert isinstance(normalized, NormalizedScanArguments)
        assert normalized.method_kwargs == {}

    def test_legacy_entry_travel_height_rejected(self):
        with pytest.raises(ValueError, match="entry_travel_height"):
            normalize_scan_arguments(
                method_kwargs={"entry_travel_height": 30.0},
            )

    def test_legacy_interwell_travel_height_rejected(self):
        with pytest.raises(ValueError, match="interwell_travel_height"):
            normalize_scan_arguments(
                method_kwargs={"interwell_travel_height": 20.0},
            )

    def test_indentation_limit_height_in_method_kwargs_rejected(self):
        """`indentation_limit_height` is a top-level scan field. Inside
        `method_kwargs` the engine wouldn't see it, so reject early."""
        with pytest.raises(ValueError, match="indentation_limit_height"):
            normalize_scan_arguments(
                method_kwargs={"indentation_limit_height": -5.0},
            )

    def test_legacy_indentation_limit_kwarg_rejected_with_rename_hint(self):
        """Old `indentation_limit` magnitude was renamed to
        `indentation_limit_height` (signed, relative)."""
        with pytest.raises(ValueError, match="indentation_limit_height"):
            normalize_scan_arguments(
                method_kwargs={"indentation_limit": 5.0},
            )

    def test_z_limit_kwarg_rejected(self):
        with pytest.raises(ValueError, match="z_limit"):
            normalize_scan_arguments(
                method_kwargs={"z_limit": 5.0},
            )

    def test_legacy_safe_approach_height_kwarg_rejected_with_rename_hint(self):
        with pytest.raises(ValueError, match="interwell_scan_height"):
            normalize_scan_arguments(
                method_kwargs={"safe_approach_height": 10.0},
            )

    def test_measurement_height_in_method_kwargs_rejected(self):
        """The dispatch surface silently overwrites a kwargs-supplied value
        with the top-level field; surface that as a load-time error rather
        than letting the user's number quietly disappear."""
        with pytest.raises(ValueError, match="measurement_height"):
            normalize_scan_arguments(
                method_kwargs={"measurement_height": 5.0},
            )

    def test_interwell_scan_height_in_method_kwargs_rejected(self):
        with pytest.raises(ValueError, match="interwell_scan_height"):
            normalize_scan_arguments(
                method_kwargs={"interwell_scan_height": 5.0},
            )
