"""Tests for ASMI indenter tip geometry config and result propagation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cubos.gantry.errors import GantryLoaderError
from cubos.gantry.gantry import Gantry
from cubos.gantry.instrument_loader import load_instrumented_gantry_from_yaml_safe
from cubos.instruments.asmi import IndenterTip, TipShape
from cubos.instruments.asmi.vendors.vernier import VernierASMI
from cubos.instruments.registry import config_fields

GANTRY_CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "gantry"


def _offline_indentation(asmi: VernierASMI, **kwargs) -> dict:
    return asmi.indentation(
        Gantry(offline=True),
        well_z=0.0,
        measurement_height=10.0,
        indentation_limit_height=9.5,
        step_size=0.1,
        **kwargs,
    )


class TestIndenterTipValidation:

    def test_spherical_tip_from_config(self):
        tip = IndenterTip.from_config(
            {"shape": "spherical", "radius_mm": 1.5875, "material": "stainless"}
        )
        assert tip.shape is TipShape.SPHERICAL
        assert tip.radius_mm == pytest.approx(1.5875)
        assert tip.material == "stainless"

    def test_flat_punch_integer_radius_is_float(self):
        tip = IndenterTip.from_config({"shape": "flat_punch", "radius_mm": 3})
        assert tip.shape is TipShape.FLAT_PUNCH
        assert isinstance(tip.radius_mm, float)
        assert tip.material is None

    def test_none_and_existing_tip_pass_through(self):
        tip = IndenterTip(shape=TipShape.SPHERICAL, radius_mm=1.0)
        assert IndenterTip.from_config(None) is None
        assert IndenterTip.from_config(tip) is tip

    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ({"radius_mm": 1.0}, r"tip\.shape is required"),
            ({"shape": "conical", "radius_mm": 1.0}, r"tip\.shape must be one of: spherical, flat_punch"),
            ({"shape": "spherical"}, r"tip\.radius_mm is required for a spherical tip"),
            ({"shape": "flat_punch", "radius_mm": None}, r"required for a flat_punch tip"),
            ({"shape": "spherical", "radius_mm": 0}, r"positive number"),
            ({"shape": "spherical", "radius_mm": -1.0}, r"positive number"),
            ({"shape": "spherical", "radius_mm": float("nan")}, r"positive number"),
            ({"shape": "spherical", "radius_mm": "1.5"}, r"must be a number"),
            ({"shape": "spherical", "radius_mm": True}, r"must be a number"),
            ({"shape": "spherical", "radius_mm": 1.0, "material": 3}, r"tip\.material must be text"),
            ({"shape": "spherical", "radius_mm": 1.0, "diameter_mm": 2.0}, r"unknown field\(s\): diameter_mm"),
            ("spherical", r"must be a mapping"),
        ],
    )
    def test_invalid_tip_config_is_rejected(self, config, message):
        with pytest.raises(ValueError, match=message):
            IndenterTip.from_config(config)


class TestVernierTip:

    def test_tip_is_optional(self):
        asmi = VernierASMI(offline=True)
        assert asmi.tip is None
        result = _offline_indentation(asmi)
        assert result["tip_shape"] is None
        assert result["tip_radius_mm"] is None
        assert result["tip_material"] is None

    def test_offline_indentation_carries_tip(self):
        asmi = VernierASMI(
            offline=True,
            tip={"shape": "spherical", "radius_mm": 1.5875, "material": "stainless"},
        )
        result = _offline_indentation(asmi)
        assert result["tip_shape"] == "spherical"
        assert result["tip_radius_mm"] == pytest.approx(1.5875)
        assert result["tip_material"] == "stainless"

    def test_online_indentation_carries_tip(self, monkeypatch):
        asmi = VernierASMI(offline=False, tip={"shape": "flat_punch", "radius_mm": 2.0})
        monkeypatch.setattr(asmi, "_move_to_indentation_start", lambda gantry, action_z: (0.0, 0.0))
        monkeypatch.setattr(asmi, "_collect_indentation_baseline", lambda baseline_samples: (0.0, 0.0))
        monkeypatch.setattr(asmi, "_run_indentation_descent", lambda gantry, **kwargs: ([], False))
        result = _offline_indentation(asmi)
        assert result["tip_shape"] == "flat_punch"
        assert result["tip_radius_mm"] == pytest.approx(2.0)

    def test_invalid_tip_fails_at_construction(self):
        with pytest.raises(ValueError, match="radius_mm"):
            VernierASMI(offline=True, tip={"shape": "spherical", "radius_mm": -2})

    def test_tip_is_not_a_flat_config_field(self):
        names = {field.name for field in config_fields("asmi", "vernier")}
        assert "tip" not in names
        assert "force_limit" in names


class TestGantryYamlTip:

    def _write_gantry(self, tmp_path: Path, tip) -> Path:
        config = yaml.safe_load((GANTRY_CONFIGS / "cub_xl_asmi.yaml").read_text())
        if tip is not None:
            config["instruments"]["asmi"]["tip"] = tip
        path = tmp_path / "gantry.yaml"
        path.write_text(yaml.safe_dump(config))
        return path

    def test_gantry_yaml_tip_block_loads(self, tmp_path):
        path = self._write_gantry(
            tmp_path, {"shape": "spherical", "radius_mm": 1.5875, "material": "stainless"},
        )
        instrumented = load_instrumented_gantry_from_yaml_safe(
            path, Gantry(offline=True), mock_mode=True,
        )
        tip = instrumented.instruments["asmi"].tip
        assert tip == IndenterTip(TipShape.SPHERICAL, 1.5875, "stainless")

    def test_gantry_yaml_bad_tip_reports_clear_error(self, tmp_path):
        path = self._write_gantry(tmp_path, {"shape": "spherical"})
        with pytest.raises(GantryLoaderError, match=r"tip\.radius_mm is required"):
            load_instrumented_gantry_from_yaml_safe(
                path, Gantry(offline=True), mock_mode=True,
            )

    @pytest.mark.parametrize(
        "name",
        ["cub_xl_asmi.yaml", "cub_xl_sterling_3_instrument.yaml", "cub_raman.yaml"],
    )
    def test_existing_asmi_gantry_configs_load_without_tip(self, name):
        instrumented = load_instrumented_gantry_from_yaml_safe(
            GANTRY_CONFIGS / name, Gantry(offline=True), mock_mode=True,
        )
        asmi_instruments = [
            inst for inst in instrumented.instruments.values()
            if isinstance(inst, VernierASMI)
        ]
        assert asmi_instruments
        assert all(inst.tip is None for inst in asmi_instruments)
