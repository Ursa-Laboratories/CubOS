"""Firmware-selection seam: config chooses the Mill (GRBL) or Duet driver."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cubos.gantry.gantry import Gantry
from cubos.gantry.gantry_config import (
    FirmwareType,
    GantryConfig,
    GantryType,
    WorkingVolume,
)
from cubos.gantry.loader import load_gantry_from_yaml


def _working_volume() -> WorkingVolume:
    return WorkingVolume(
        x_min=0.0, x_max=400.0, y_min=0.0, y_max=300.0, z_min=0.0, z_max=110.0
    )


@patch("cubos.gantry.gantry.DuetDriver")
@patch("cubos.gantry.gantry.Mill")
def test_default_config_selects_grbl_mill(mock_mill, mock_duet):
    Gantry(config={})
    mock_mill.assert_called_once()
    mock_duet.assert_not_called()


@patch("cubos.gantry.gantry.DuetDriver")
@patch("cubos.gantry.gantry.Mill")
def test_dict_config_selects_duet(mock_mill, mock_duet):
    Gantry(config={"firmware": "duet", "serial_port": "/dev/ttyACM0"})
    mock_duet.assert_called_once()
    mock_mill.assert_not_called()


@patch("cubos.gantry.gantry.DuetDriver")
@patch("cubos.gantry.gantry.Mill")
def test_dataclass_config_selects_duet(mock_mill, mock_duet):
    config = GantryConfig(
        serial_port="/dev/ttyACM0",
        gantry_type=GantryType.CUB_XL,
        factory_z_travel_mm=110.0,
        working_volume=_working_volume(),
        firmware=FirmwareType.DUET,
    )
    Gantry(config=config)
    mock_duet.assert_called_once()
    mock_mill.assert_not_called()


@patch("cubos.gantry.gantry.DuetDriver")
@patch("cubos.gantry.gantry.Mill")
def test_offline_gantry_builds_no_driver(mock_mill, mock_duet):
    Gantry(config={"firmware": "duet"}, offline=True)
    mock_mill.assert_not_called()
    mock_duet.assert_not_called()


def test_unknown_firmware_rejected():
    with pytest.raises(ValueError, match="Unsupported firmware"):
        Gantry(config={"firmware": "klipper"})


def test_gantry_config_rejects_unknown_firmware():
    with pytest.raises(ValueError, match="Unsupported firmware"):
        GantryConfig(
            serial_port="",
            gantry_type=GantryType.CUB_XL,
            factory_z_travel_mm=110.0,
            working_volume=_working_volume(),
            firmware="klipper",
        )


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

_BASE_YAML = """
serial_port: "/dev/ttyACM0"
gantry_type: cub_xl
{firmware_line}
cnc:
  factory_z_travel_mm: 110.0
  y_axis_motion: head
working_volume:
  x_min: 0.0
  x_max: 400.0
  y_min: 0.0
  y_max: 300.0
  z_min: 0.0
  z_max: 110.0
{extra}
instruments: {{}}
"""


def _write_yaml(tmp_path, firmware_line="", extra=""):
    path = tmp_path / "gantry.yaml"
    path.write_text(_BASE_YAML.format(firmware_line=firmware_line, extra=extra))
    return path


def test_yaml_defaults_to_grbl(tmp_path):
    config = load_gantry_from_yaml(_write_yaml(tmp_path))
    assert config.firmware is FirmwareType.GRBL


def test_yaml_firmware_duet(tmp_path):
    config = load_gantry_from_yaml(
        _write_yaml(tmp_path, firmware_line="firmware: duet")
    )
    assert config.firmware is FirmwareType.DUET


def test_yaml_rejects_grbl_settings_with_duet_firmware(tmp_path):
    path = _write_yaml(
        tmp_path,
        firmware_line="firmware: duet",
        extra="grbl_settings:\n  homing_pull_off: 3.0",
    )
    with pytest.raises(Exception, match="grbl_settings cannot be used"):
        load_gantry_from_yaml(path)


def test_yaml_rejects_unknown_firmware(tmp_path):
    path = _write_yaml(tmp_path, firmware_line="firmware: klipper")
    with pytest.raises(Exception):
        load_gantry_from_yaml(path)
