"""Offline tests for packages/core/src/cubos/tools/hello_world.py."""

from __future__ import annotations

import builtins
import sys

import pytest

from cubos.gantry.errors import CommandExecutionError
from cubos.tools import hello_world


class _BaseHelloGantry:
    instance: "_BaseHelloGantry"

    def __init__(self, config: dict):
        self.config = config
        self.calls: list[tuple] = []
        self.coords = {"x": 0.0, "y": 0.0, "z": 0.0}
        _BaseHelloGantry.instance = self

    def connect(self) -> None:
        self.calls.append(("connect",))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    def is_healthy(self) -> bool:
        self.calls.append(("is_healthy",))
        return True

    def get_status(self) -> str:
        self.calls.append(("get_status",))
        return "Idle"

    def home(self) -> None:
        self.calls.append(("home",))

    def get_coordinates(self) -> dict[str, float]:
        self.calls.append(("get_coordinates",))
        return dict(self.coords)

    def jog(self, x: float = 0, y: float = 0, z: float = 0) -> None:
        self.calls.append(("jog", x, y, z))
        self.coords = {
            "x": self.coords["x"] + x,
            "y": self.coords["y"] + y,
            "z": self.coords["z"] + z,
        }

    def stop(self) -> None:
        self.calls.append(("stop",))


class _StartupAlarmGantry(_BaseHelloGantry):
    def is_healthy(self) -> bool:
        self.calls.append(("is_healthy",))
        return False

    def get_status(self) -> str:
        self.calls.append(("get_status",))
        return "<Alarm|WPos:0,0,0>"


class _RejectingJogGantry(_BaseHelloGantry):
    def __init__(self, config: dict):
        super().__init__(config)
        self.reject_next_jog = True

    def jog(self, x: float = 0, y: float = 0, z: float = 0) -> None:
        self.calls.append(("jog", x, y, z))
        if self.reject_next_jog:
            self.reject_next_jog = False
            raise CommandExecutionError("Jog failed: error:15")
        super().jog(x=x, y=y, z=z)


class _UnhealthyGantry(_BaseHelloGantry):
    def is_healthy(self) -> bool:
        self.calls.append(("is_healthy",))
        return False

    def get_status(self) -> str:
        self.calls.append(("get_status",))
        return "<Idle|WPos:0,0,0>"


def _run_hello_world(monkeypatch, tmp_path, gantry_cls, keys: list[str]) -> str:
    gantry_path = tmp_path / "gantry.yaml"
    gantry_path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    key_iter = iter(keys)

    monkeypatch.setattr(sys, "argv", ["hello_world.py", "--gantry", str(gantry_path)])
    monkeypatch.setattr(hello_world, "Gantry", gantry_cls)
    monkeypatch.setattr(hello_world, "load_gantry_from_yaml_safe", lambda _path: {})
    monkeypatch.setattr(hello_world, "validate_deck_origin_minima", lambda _config: None)
    monkeypatch.setattr(hello_world, "read_keypress", lambda: next(key_iter))
    monkeypatch.setattr(hello_world, "flush_stdin", lambda: None)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "")

    hello_world.main()
    return ""


def test_hello_world_startup_alarm_proceeds_to_homing(monkeypatch, tmp_path, capsys):
    _run_hello_world(monkeypatch, tmp_path, _StartupAlarmGantry, ["Q"])

    calls = _StartupAlarmGantry.instance.calls
    assert ("home",) in calls
    assert ("disconnect",) in calls
    assert "startup alarm" in capsys.readouterr().out


def test_hello_world_soft_limit_rejected_jog_prints_guidance_and_continues(
    monkeypatch,
    tmp_path,
    capsys,
):
    _run_hello_world(monkeypatch, tmp_path, _RejectingJogGantry, ["RIGHT", "Q"])

    calls = _RejectingJogGantry.instance.calls
    assert ("jog", hello_world.STEP, 0, 0) in calls
    assert ("disconnect",) in calls
    output = capsys.readouterr().out
    assert "exceeds current travel" in output
    assert "Done." in output


def test_hello_world_missing_config_exits_1(monkeypatch, tmp_path, capsys):
    missing = tmp_path / "missing.yaml"
    monkeypatch.setattr(sys, "argv", ["hello_world.py", "--gantry", str(missing)])

    with pytest.raises(SystemExit) as exc_info:
        hello_world.main()

    assert exc_info.value.code == 1
    assert "Gantry config not found" in capsys.readouterr().err


def test_hello_world_unhealthy_non_alarm_disconnects_and_exits(monkeypatch, tmp_path):
    gantry_path = tmp_path / "gantry.yaml"
    gantry_path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["hello_world.py", "--gantry", str(gantry_path)])
    monkeypatch.setattr(hello_world, "Gantry", _UnhealthyGantry)
    monkeypatch.setattr(hello_world, "load_gantry_from_yaml_safe", lambda _path: {})
    monkeypatch.setattr(hello_world, "validate_deck_origin_minima", lambda _config: None)

    with pytest.raises(SystemExit) as exc_info:
        hello_world.main()

    assert exc_info.value.code == 1
    assert ("disconnect",) in _UnhealthyGantry.instance.calls


def test_hello_world_keyboard_interrupt_stops_and_disconnects(monkeypatch, tmp_path, capsys):
    gantry_path = tmp_path / "gantry.yaml"
    gantry_path.write_text("serial_port: /dev/fake\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["hello_world.py", "--gantry", str(gantry_path)])
    monkeypatch.setattr(hello_world, "Gantry", _BaseHelloGantry)
    monkeypatch.setattr(hello_world, "load_gantry_from_yaml_safe", lambda _path: {})
    monkeypatch.setattr(hello_world, "validate_deck_origin_minima", lambda _config: None)
    monkeypatch.setattr(hello_world, "read_keypress", lambda: (_ for _ in ()).throw(KeyboardInterrupt))
    monkeypatch.setattr(hello_world, "flush_stdin", lambda: None)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "")

    hello_world.main()

    assert ("stop",) in _BaseHelloGantry.instance.calls
    assert ("disconnect",) in _BaseHelloGantry.instance.calls
    assert "Interrupted" in capsys.readouterr().out


def test_looks_like_soft_limit_jog_rejection_negative_case():
    assert not hello_world._looks_like_soft_limit_jog_rejection(RuntimeError("port closed"))
