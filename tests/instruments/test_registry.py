import pytest

from instruments.registry import (
    get_instrument_class,
    get_supported_types,
    get_supported_vendors,
    load_registry,
    validate_instrument,
)
from instruments.base_instrument import BaseInstrument


EXPECTED_TYPES = [
    "asmi",
    "filmetrics",
    "pipette",
    "potentiostat",
    "rpi_camera",
    "uv_curing",
    "uvvis_ccs",
]


class TestLoadRegistry:

    def test_returns_all_instrument_types(self):
        registry = load_registry()
        assert sorted(registry["instruments"].keys()) == EXPECTED_TYPES

    def test_each_entry_has_vendors(self):
        registry = load_registry()
        for type_key, entry in registry["instruments"].items():
            assert "vendors" in entry, f"{type_key} missing vendors"
            assert len(entry["vendors"]) > 0, f"{type_key} has empty vendors"

    def test_each_entry_has_module_and_class(self):
        registry = load_registry()
        for type_key, entry in registry["instruments"].items():
            assert "module" in entry, f"{type_key} missing module"
            assert "class_name" in entry, f"{type_key} missing class_name"


class TestGetSupportedTypes:

    def test_returns_sorted_list(self):
        assert get_supported_types() == EXPECTED_TYPES


class TestGetSupportedVendors:

    def test_asmi_vendors(self):
        assert get_supported_vendors("asmi") == ["vernier"]

    def test_filmetrics_vendors(self):
        assert get_supported_vendors("filmetrics") == ["kla"]

    def test_pipette_vendors(self):
        assert get_supported_vendors("pipette") == ["opentrons"]

    def test_potentiostat_vendors(self):
        assert get_supported_vendors("potentiostat") == ["admiral"]

    def test_rpi_camera_vendors(self):
        assert get_supported_vendors("rpi_camera") == ["raspberry_pi"]

    def test_uv_curing_vendors(self):
        assert get_supported_vendors("uv_curing") == ["excelitas"]

    def test_uvvis_ccs_vendors(self):
        assert get_supported_vendors("uvvis_ccs") == ["thorlabs"]

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown instrument type"):
            get_supported_vendors("nonexistent")


class TestGetInstrumentClass:

    def test_returns_subclass_of_base_instrument(self):
        for type_key in EXPECTED_TYPES:
            cls = get_instrument_class(type_key)
            assert issubclass(cls, BaseInstrument), f"{type_key} class not a BaseInstrument"

    def test_asmi_class(self):
        from instruments.asmi.driver import ASMI
        assert get_instrument_class("asmi") is ASMI

    def test_filmetrics_class(self):
        from instruments.filmetrics.driver import Filmetrics
        assert get_instrument_class("filmetrics") is Filmetrics

    def test_pipette_class(self):
        from instruments.pipette.driver import Pipette
        assert get_instrument_class("pipette") is Pipette

    def test_potentiostat_class(self):
        from instruments.potentiostat.driver import Potentiostat
        assert get_instrument_class("potentiostat") is Potentiostat

    def test_rpi_camera_class(self):
        from instruments.rpi_camera.driver import RPiCamera
        assert get_instrument_class("rpi_camera") is RPiCamera

    def test_uv_curing_class(self):
        from instruments.uv_curing.driver import UVCuring
        assert get_instrument_class("uv_curing") is UVCuring

    def test_uvvis_ccs_class(self):
        from instruments.uvvis_ccs.driver import UVVisCCS
        assert get_instrument_class("uvvis_ccs") is UVVisCCS

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown instrument type"):
            get_instrument_class("nonexistent")


class TestValidateInstrument:

    def test_valid_combinations_pass(self):
        valid_pairs = [
            ("asmi", "vernier"),
            ("filmetrics", "kla"),
            ("pipette", "opentrons"),
            ("potentiostat", "admiral"),
            ("rpi_camera", "raspberry_pi"),
            ("uv_curing", "excelitas"),
            ("uvvis_ccs", "thorlabs"),
        ]
        for type_key, vendor in valid_pairs:
            validate_instrument(type_key, vendor)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown instrument type"):
            validate_instrument("nonexistent", "some_vendor")

    def test_wrong_vendor_raises(self):
        with pytest.raises(ValueError, match="not a supported vendor"):
            validate_instrument("uvvis_ccs", "wrong_vendor")

    def test_wrong_vendor_message_lists_allowed(self):
        with pytest.raises(ValueError, match="thorlabs"):
            validate_instrument("uvvis_ccs", "wrong_vendor")
