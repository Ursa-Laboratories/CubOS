import textwrap

import pytest

import instruments.registry as registry_module
from instruments.asmi.interface import ASMIInstrument
from instruments.base_instrument import BaseInstrument
from instruments.pipette.interface import PipetteInstrument
from instruments.registry import (
    get_calibration_mode,
    get_instrument_class,
    get_instrument_interface,
    get_supported_types,
    get_supported_vendors,
    load_registry,
    validate_instrument,
)


EXPECTED_TYPES = [
    "asmi",
    "camera",
    "filmetrics",
    "mounted_tool",
    "pipette",
    "potentiostat",
    "uv_curing",
    "uvvis_ccs",
]


class FakeCustomerASMI(ASMIInstrument):
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        return True


class FakeCustomerPipette(PipetteInstrument):
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        return True


class _EntryPointGroup:
    def __init__(self, entries):
        self._entries = entries

    def select(self, *, group: str):
        if group == "cubos.instrument_registries":
            return self._entries
        return []


class _EntryPoint:
    name = "customer_registry"

    def __init__(self, registry):
        self._registry = registry

    def load(self):
        return self._registry


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch):
    monkeypatch.delenv("CUBOS_INSTRUMENT_REGISTRY_PATHS", raising=False)
    monkeypatch.setattr(
        registry_module.importlib_metadata,
        "entry_points",
        lambda: _EntryPointGroup([]),
    )
    registry_module._cache = None
    yield
    registry_module._cache = None


class TestLoadRegistry:

    def test_returns_all_instrument_types(self):
        registry = load_registry()
        assert sorted(registry["instruments"].keys()) == EXPECTED_TYPES

    def test_each_entry_has_interface_calibration_mode_and_vendors(self):
        registry = load_registry()
        for type_key, entry in registry["instruments"].items():
            assert "interface" in entry, f"{type_key} missing interface"
            assert entry.get("calibration_mode") in {"contact", "non_contact"}
            assert "vendors" in entry, f"{type_key} missing vendors"
            assert len(entry["vendors"]) > 0, f"{type_key} has empty vendors"
            for vendor_key, vendor in entry["vendors"].items():
                assert "module" in vendor, f"{type_key}/{vendor_key} missing module"
                assert "class_name" in vendor, (
                    f"{type_key}/{vendor_key} missing class_name"
                )

    def test_overlay_adds_vendor_for_existing_type(self, tmp_path, monkeypatch):
        overlay = tmp_path / "instrument_registry.yaml"
        overlay.write_text(
            textwrap.dedent(
                """
                instruments:
                  asmi:
                    vendors:
                      customer_xyz:
                        module: tests.instruments.test_registry
                        class_name: FakeCustomerASMI
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CUBOS_INSTRUMENT_REGISTRY_PATHS", str(overlay))
        registry_module._cache = None

        assert "customer_xyz" in get_supported_vendors("asmi")
        assert get_instrument_class("asmi", "customer_xyz") is FakeCustomerASMI

    def test_entry_point_adds_vendor(self, monkeypatch):
        monkeypatch.setattr(
            registry_module.importlib_metadata,
            "entry_points",
            lambda: _EntryPointGroup([
                _EntryPoint({
                    "instruments": {
                        "pipette": {
                            "vendors": {
                                "customer_xyz": {
                                    "module": "tests.instruments.test_registry",
                                    "class_name": "FakeCustomerPipette",
                                }
                            }
                        }
                    }
                })
            ]),
        )
        registry_module._cache = None

        assert "customer_xyz" in get_supported_vendors("pipette")
        assert get_instrument_class("pipette", "customer_xyz") is FakeCustomerPipette

    def test_duplicate_vendor_without_override_raises(self, tmp_path, monkeypatch):
        overlay = tmp_path / "instrument_registry.yaml"
        overlay.write_text(
            textwrap.dedent(
                """
                instruments:
                  asmi:
                    vendors:
                      vernier:
                        module: tests.instruments.test_registry
                        class_name: FakeCustomerASMI
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CUBOS_INSTRUMENT_REGISTRY_PATHS", str(overlay))
        registry_module._cache = None

        with pytest.raises(ValueError, match="already registered"):
            load_registry()

    def test_duplicate_vendor_with_override_replaces(self, tmp_path, monkeypatch):
        overlay = tmp_path / "instrument_registry.yaml"
        overlay.write_text(
            textwrap.dedent(
                """
                instruments:
                  asmi:
                    vendors:
                      vernier:
                        override: true
                        module: tests.instruments.test_registry
                        class_name: FakeCustomerASMI
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CUBOS_INSTRUMENT_REGISTRY_PATHS", str(overlay))
        registry_module._cache = None

        assert get_instrument_class("asmi", "vernier") is FakeCustomerASMI


class TestGetSupportedTypes:

    def test_returns_sorted_list(self):
        assert get_supported_types() == EXPECTED_TYPES


class TestGetSupportedVendors:

    def test_asmi_vendors(self):
        assert get_supported_vendors("asmi") == ["vernier"]

    def test_camera_vendors(self):
        assert get_supported_vendors("camera") == ["mount_only", "raspberry_pi"]

    def test_filmetrics_vendors(self):
        assert get_supported_vendors("filmetrics") == ["kla"]

    def test_mounted_tool_vendors(self):
        assert get_supported_vendors("mounted_tool") == ["mount_only"]

    def test_pipette_vendors(self):
        assert get_supported_vendors("pipette") == ["opentrons"]

    def test_potentiostat_vendors(self):
        assert get_supported_vendors("potentiostat") == ["admiral"]

    def test_uv_curing_vendors(self):
        assert get_supported_vendors("uv_curing") == ["excelitas"]

    def test_uvvis_ccs_vendors(self):
        assert get_supported_vendors("uvvis_ccs") == ["thorlabs"]

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown instrument type"):
            get_supported_vendors("nonexistent")


class TestGetCalibrationMode:
    def test_camera_is_non_contact(self):
        assert get_calibration_mode("camera") == "non_contact"

    def test_contact_is_default_for_regular_instruments(self):
        assert get_calibration_mode("asmi") == "contact"


class TestGetInstrumentClass:

    def test_returns_subclass_of_base_instrument(self):
        valid_pairs = [
            ("asmi", "vernier"),
            ("camera", "mount_only"),
            ("camera", "raspberry_pi"),
            ("filmetrics", "kla"),
            ("mounted_tool", "mount_only"),
            ("pipette", "opentrons"),
            ("potentiostat", "admiral"),
            ("uv_curing", "excelitas"),
            ("uvvis_ccs", "thorlabs"),
        ]
        for type_key, vendor in valid_pairs:
            cls = get_instrument_class(type_key, vendor)
            assert issubclass(cls, BaseInstrument)
            assert issubclass(cls, get_instrument_interface(type_key))

    def test_asmi_class(self):
        from instruments.asmi.vendors.vernier import VernierASMI
        assert get_instrument_class("asmi", "vernier") is VernierASMI

    def test_camera_class(self):
        from instruments.camera.vendors.raspberry_pi import RaspberryPiCamera
        assert get_instrument_class("camera", "raspberry_pi") is RaspberryPiCamera

    def test_mount_only_camera_class(self):
        from instruments.camera.vendors.mount_only import MountOnlyCamera
        assert get_instrument_class("camera", "mount_only") is MountOnlyCamera

    def test_filmetrics_class(self):
        from instruments.filmetrics.vendors.kla import KLAFilmetrics
        assert get_instrument_class("filmetrics", "kla") is KLAFilmetrics

    def test_mounted_tool_class(self):
        from instruments.mounted_tool.vendors.mount_only import MountOnlyTool
        assert get_instrument_class("mounted_tool", "mount_only") is MountOnlyTool

    def test_pipette_class(self):
        from instruments.pipette.vendors.opentrons import OpentronsPipette
        assert get_instrument_class("pipette", "opentrons") is OpentronsPipette

    def test_potentiostat_class(self):
        from instruments.potentiostat.vendors.admiral import AdmiralPotentiostat
        assert get_instrument_class("potentiostat", "admiral") is AdmiralPotentiostat

    def test_uv_curing_class(self):
        from instruments.uv_curing.vendors.excelitas import ExcelitasUVCuring
        assert get_instrument_class("uv_curing", "excelitas") is ExcelitasUVCuring

    def test_uvvis_ccs_class(self):
        from instruments.uvvis_ccs.vendors.thorlabs import ThorlabsUVVisCCS
        assert get_instrument_class("uvvis_ccs", "thorlabs") is ThorlabsUVVisCCS

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown instrument type"):
            get_instrument_class("nonexistent", "some_vendor")


class TestValidateInstrument:

    def test_valid_combinations_pass(self):
        valid_pairs = [
            ("asmi", "vernier"),
            ("camera", "mount_only"),
            ("camera", "raspberry_pi"),
            ("filmetrics", "kla"),
            ("mounted_tool", "mount_only"),
            ("pipette", "opentrons"),
            ("potentiostat", "admiral"),
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
