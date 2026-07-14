"""Offline tests for setup homing/validation CLI wrappers."""

from __future__ import annotations

import sys

import pytest

from cubos.gantry.offline import OfflineGantry
from cubos.tools import home_gantry_config, validate_setup


class _FakeHomingGantry:
    instance: "_FakeHomingGantry"

    def __init__(self, config):
        self.config = config
        self.calls: list[str] = []
        _FakeHomingGantry.instance = self

    def connect(self) -> None:
        self.calls.append("connect")

    def home(self) -> None:
        self.calls.append("home")

    def disconnect(self) -> None:
        self.calls.append("disconnect")


class _FailingHomeGantry(_FakeHomingGantry):
    def home(self) -> None:
        self.calls.append("home")
        raise RuntimeError("limit switch")


def test_offline_gantry_tracks_coordinates_without_hardware():
    gantry = OfflineGantry()

    assert gantry.is_healthy()
    assert gantry.get_status() == "Idle"
    assert gantry.get_coordinates() == {"x": 0.0, "y": 0.0, "z": 0.0}

    gantry.connect()
    gantry.home()
    gantry.unlock()
    gantry.move_to(1.0, 2.0, 3.0, travel_z=9.0)
    gantry.stop()
    gantry.feed_hold_realtime()
    gantry.resume()
    gantry.disconnect()

    assert gantry.get_coordinates() == {"x": 1.0, "y": 2.0, "z": 3.0}


def test_home_gantry_config_run_homing_disconnects_after_home(monkeypatch, tmp_path):
    path = tmp_path / "gantry.yaml"
    path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    monkeypatch.setattr(home_gantry_config, "load_gantry_from_yaml_safe", lambda p: {"path": p})
    monkeypatch.setattr(home_gantry_config, "validate_deck_origin_minima", lambda _config: None)
    monkeypatch.setattr(home_gantry_config, "Gantry", _FakeHomingGantry)

    home_gantry_config.run_homing(path)

    assert _FakeHomingGantry.instance.config == {"path": path}
    assert _FakeHomingGantry.instance.calls == ["connect", "home", "disconnect"]


def test_home_gantry_config_run_homing_disconnects_after_failure(monkeypatch, tmp_path):
    path = tmp_path / "gantry.yaml"
    path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    monkeypatch.setattr(home_gantry_config, "load_gantry_from_yaml_safe", lambda _path: {})
    monkeypatch.setattr(home_gantry_config, "validate_deck_origin_minima", lambda _config: None)
    monkeypatch.setattr(home_gantry_config, "Gantry", _FailingHomeGantry)

    with pytest.raises(RuntimeError, match="limit switch"):
        home_gantry_config.run_homing(path)

    assert _FailingHomeGantry.instance.calls == ["connect", "home", "disconnect"]


def test_home_gantry_config_main_rejects_missing_file(monkeypatch, tmp_path, capsys):
    missing = tmp_path / "missing.yaml"
    monkeypatch.setattr(sys, "argv", ["home_gantry_config.py", "--gantry", str(missing)])

    with pytest.raises(SystemExit) as exc_info:
        home_gantry_config.main()

    assert exc_info.value.code == 1
    assert "Gantry config not found" in capsys.readouterr().err


def test_home_gantry_config_main_reports_keyboard_interrupt(monkeypatch, tmp_path, capsys):
    path = tmp_path / "gantry.yaml"
    path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["home_gantry_config.py", "--gantry", str(path)])
    monkeypatch.setattr(home_gantry_config, "run_homing", lambda _path: (_ for _ in ()).throw(KeyboardInterrupt))

    with pytest.raises(SystemExit) as exc_info:
        home_gantry_config.main()

    assert exc_info.value.code == 130
    assert "Aborted." in capsys.readouterr().out


def test_home_gantry_config_main_reports_homing_error(monkeypatch, tmp_path, capsys):
    path = tmp_path / "gantry.yaml"
    path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["home_gantry_config.py", "--gantry", str(path)])
    monkeypatch.setattr(home_gantry_config, "run_homing", lambda _path: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(SystemExit) as exc_info:
        home_gantry_config.main()

    assert exc_info.value.code == 1
    assert "ERROR: boom" in capsys.readouterr().err


def test_home_gantry_config_main_happy_path(monkeypatch, tmp_path, capsys):
    path = tmp_path / "gantry.yaml"
    path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    seen: list[str] = []
    monkeypatch.setattr(sys, "argv", ["home_gantry_config.py", "--gantry", str(path)])
    monkeypatch.setattr(home_gantry_config, "run_homing", lambda p: seen.append(str(p)))

    home_gantry_config.main()

    assert seen == [str(path.resolve())]
    assert "Done." in capsys.readouterr().out


def test_validate_setup_usage_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["validate_setup.py", "only-one.yaml"])

    with pytest.raises(SystemExit) as exc_info:
        validate_setup.main()

    assert exc_info.value.code == 1
    assert "Usage: python -m cubos.tools.validate_setup" in capsys.readouterr().out


def test_validate_setup_pass_prints_output(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["validate_setup.py", "g.yaml", "d.yaml", "p.yaml"])
    monkeypatch.setattr(
        validate_setup,
        "run_setup_validation",
        lambda *args: validate_setup.SetupValidationResult(output="PASS: checked", passed=True),
    )

    validate_setup.main()

    assert "PASS: checked" in capsys.readouterr().out


def test_validate_setup_fail_prints_output_and_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["validate_setup.py", "g.yaml", "d.yaml", "p.yaml"])
    monkeypatch.setattr(
        validate_setup,
        "run_setup_validation",
        lambda *args: validate_setup.SetupValidationResult(output="FAIL: bad bounds", passed=False),
    )

    with pytest.raises(SystemExit) as exc_info:
        validate_setup.main()

    assert exc_info.value.code == 1
    assert "FAIL: bad bounds" in capsys.readouterr().out
