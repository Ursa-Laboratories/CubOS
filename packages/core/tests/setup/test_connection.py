"""Unit tests for setup/test_connection.py helper functions.

These tests use Gantry(offline=True) — no hardware required.
"""

from __future__ import annotations

import textwrap
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from cubos.gantry.gantry import Gantry


class TestFormatGrblSettings:
    """Verify the GRBL-settings formatter used in the connection report."""

    def test_formats_known_settings(self):
        from cubos.tools.test_connection import format_grbl_settings

        raw = {"$100": "800.000", "$110": "2000.000", "$130": "400.000"}
        lines = format_grbl_settings(raw)
        assert any("$100" in line and "800" in line for line in lines)
        assert len(lines) == 3

    def test_empty_settings(self):
        from cubos.tools.test_connection import format_grbl_settings

        assert format_grbl_settings({}) == []


class TestConnectionReport:
    """Verify the report builder produces the expected sections."""

    def test_report_contains_required_sections(self):
        from cubos.tools.test_connection import build_connection_report

        report = build_connection_report(
            port="/dev/tty.usbserial-130",
            status="<Idle|WPos:0.000,0.000,0.000|Bf:15,127>",
            coordinates={"x": 0.0, "y": 0.0, "z": 0.0},
            healthy=True,
            grbl_settings={"$100": "800.000"},
            alarm=False,
        )
        assert "Connection" in report
        assert "/dev/tty.usbserial-130" in report
        assert "Healthy" in report
        assert "Idle" in report

    def test_report_shows_alarm(self):
        from cubos.tools.test_connection import build_connection_report

        report = build_connection_report(
            port="/dev/tty.usbserial-130",
            status="<Alarm|WPos:0.000,0.000,0.000>",
            coordinates={"x": 0.0, "y": 0.0, "z": 0.0},
            healthy=False,
            grbl_settings={},
            alarm=True,
        )
        assert "ALARM" in report or "Alarm" in report


class TestOfflineGantryConnection:
    """Verify that the Gantry wrapper works in offline mode."""

    def test_offline_gantry_is_healthy(self):
        gantry = Gantry(config={}, offline=True)
        assert gantry.is_healthy()

    def test_offline_gantry_returns_coordinates(self):
        gantry = Gantry(config={}, offline=True)
        coords = gantry.get_coordinates()
        assert coords == {"x": 0.0, "y": 0.0, "z": 0.0}


class TestCollectConnectionInfo:
    """Verify the connection script uses the public Gantry boundary."""

    def test_collect_uses_gantry_port_override_and_report_methods(self, tmp_path):
        import cubos.tools.test_connection as module

        config_dir = tmp_path / "configs" / "gantry"
        config_dir.mkdir(parents=True)
        (config_dir / "test_gantry.yaml").write_text(
            "serial_port: /dev/from-config\n",
            encoding="utf-8",
        )
        fake_gantry = MagicMock()
        fake_gantry.is_healthy.return_value = True
        fake_gantry.get_coordinates.return_value = {"x": 1.0, "y": 2.0, "z": 3.0}
        fake_gantry.get_status.return_value = "<Idle|WPos:1.000,2.000,3.000>"
        fake_gantry.read_grbl_settings.return_value = {"$20": "1"}
        fake_gantry.connected_port.return_value = "/dev/tty.usbserial-130"

        with patch.object(module, "project_root", tmp_path), patch.object(
            module, "Gantry", return_value=fake_gantry
        ) as gantry_cls:
            report = module._collect_connection_info(
                "test_gantry",
                "/dev/requested",
            )

        gantry_cls.assert_called_once_with(config={"serial_port": "/dev/from-config"})
        fake_gantry.connect.assert_called_once_with(port="/dev/requested")
        fake_gantry.read_grbl_settings.assert_called_once_with()
        fake_gantry.connected_port.assert_called_once_with()
        assert "Connection: /dev/tty.usbserial-130" in report
