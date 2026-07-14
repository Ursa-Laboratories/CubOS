"""Image smoke test: ``/api/v1/gantry/connect`` under an unwritable ``$HOME``.

Regression for the appliance-monorepo Docker image. The runtime user's home
directory was ``/nonexistent`` (unwritable), but the gantry driver's logger
defaulted its log dir to ``~/.cubos/logs/gantry`` and created it eagerly on
connect. Result: connecting the gantry crashed with
``[Errno 13] Permission denied: '/nonexistent'`` and ``/connect`` returned 500.

This drives the *real* path — ``GantrySession`` -> ``Gantry`` -> ``Mill`` ->
gantry logger — over a fake GRBL serial device, with the default log dir made
unwritable, and asserts the endpoint still connects. Forensic logging degrades
to a temp fallback instead of taking down the mill.

The fake serial is a self-contained port of ``tests.gantry.fake_serial`` from
``packages/core`` (not importable here — only ``packages/core/src`` is on the
test path), trimmed to the handshake this test exercises.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest
import serial.tools.list_ports

from cubos.gantry.gantry_driver import driver as gantry_driver
from cubos.gantry.gantry_driver import logger as gantry_logger

from tests.api_client import api_request
from cubos_api.app import create_app
from cubos_api.config import get_settings
from cubos_api.routers import gantry as gantry_router
from cubos_api.services.yaml_io import write_yaml


# GRBL settings the config below expects the controller to report (see
# Gantry._expected_grbl_settings); the fake must echo matching values or
# connect() fails the critical-settings check for reasons unrelated to logging.
_FAKE_GRBL_SETTINGS = {
    "$20": "1",
    "$22": "1",
    "$130": "310.000",
    "$131": "210.000",
    "$132": "90.000",
}

VALID_GANTRY = {
    "serial_port": "/dev/fake-grbl",
    "gantry_type": "cub_xl",
    "cnc": {"factory_z_travel_mm": 110.0, "calibration_block_height_mm": 35.0},
    "working_volume": {
        "x_min": 0.0, "x_max": 300.0,
        "y_min": 0.0, "y_max": 200.0,
        "z_min": 0.0, "z_max": 80.0,
    },
    "grbl_settings": {
        "soft_limits": True,
        "homing_enable": True,
        "max_travel_x": 310.0,
        "max_travel_y": 210.0,
        "max_travel_z": 90.0,
    },
    "instruments": {},
}


class FakeGrblSerial:
    """Minimal scriptable pyserial double with GRBL-style responses."""

    def __init__(self, *args, **kwargs):
        self.port = kwargs.get("port", "/dev/fake-grbl")
        self.timeout = kwargs.get("timeout", 2)
        self.is_open = True
        self.status = "<Idle|WPos:0.000,0.000,0.000|WCO:0.000,0.000,0.000|FS:0,0>"
        self.settings = dict(_FAKE_GRBL_SETTINGS)
        self.writes: list[bytes] = []
        self._rx: deque[bytes] = deque()

    @property
    def in_waiting(self) -> int:
        return sum(len(item) for item in self._rx)

    def _queue_line(self, value: str) -> None:
        self._rx.append((value if value.endswith("\r\n") else f"{value}\r\n").encode())

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"?":
            self._queue_line(self.status)
        elif data == b"\x18":
            self._queue_line("Grbl 1.1h ['$' for help]")
        else:
            command = data.decode("ascii", errors="ignore").strip()
            if command == "$$":
                for key, value in self.settings.items():
                    self._queue_line(f"{key}={value}")
                self._queue_line("ok")
            elif command == "$N":
                self._queue_line("$N0=")
                self._queue_line("$N1=")
                self._queue_line("ok")
            elif command:
                self._queue_line("ok")
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self._rx:
            return b""
        data = self._rx.popleft()
        head, tail = data[:size], data[size:]
        if tail:
            self._rx.appendleft(tail)
        return head

    def readline(self) -> bytes:
        if not self._rx:
            return b""
        data = bytearray()
        while self._rx:
            chunk = self._rx.popleft()
            if b"\n" in chunk:
                idx = chunk.index(b"\n") + 1
                data.extend(chunk[:idx])
                tail = chunk[idx:]
                if tail:
                    self._rx.appendleft(tail)
                break
            data.extend(chunk)
        return bytes(data)

    def readlines(self) -> list[bytes]:
        lines = []
        while self._rx:
            lines.append(self.readline())
        return lines

    def read_all(self) -> bytes:
        data = b"".join(self._rx)
        self._rx.clear()
        return data

    def flushInput(self) -> None:
        self._rx.clear()

    def flushOutput(self) -> None:
        pass

    def flush(self) -> None:
        pass


def test_connect_succeeds_when_home_log_dir_is_unwritable(monkeypatch, tmp_path):
    # --- Gantry config on disk, selected by /connect ---
    config_dir = tmp_path / "configs"
    gantry_dir = config_dir / "gantry"
    gantry_dir.mkdir(parents=True)
    write_yaml(gantry_dir / "cub.yaml", VALID_GANTRY)
    monkeypatch.setattr(get_settings(), "config_dir", config_dir)

    # Fresh module-level session so /connect builds a real GantrySession.
    monkeypatch.setattr(gantry_router, "_session", None)

    # --- Reproduce the hardened-container filesystem ---
    # Default log dir points at an unwritable HOME; temp fallback redirected
    # into the test's tmp so we can assert forensic logging still lands.
    monkeypatch.setattr(
        gantry_logger, "DEFAULT_LOG_DIR", Path("/nonexistent/.cubos/logs/gantry")
    )
    fallback_root = tmp_path / "tmp"
    fallback_root.mkdir()
    monkeypatch.setattr(
        gantry_logger.tempfile, "gettempdir", lambda: str(fallback_root)
    )
    monkeypatch.delenv(gantry_logger.GANTRY_LOG_DIR_ENV, raising=False)

    # --- Fake serial device; no real sleeps or port scanning ---
    monkeypatch.setattr(gantry_driver.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(gantry_driver.serial, "Serial", FakeGrblSerial)
    monkeypatch.setattr(
        serial.tools.list_ports, "grep", lambda *_a, **_k: iter(())
    )

    response = api_request(
        create_app(),
        "POST",
        "/api/v1/gantry/connect",
        json={"filename": "cub.yaml"},
    )

    # Before the fix this returned 500 "Failed to connect: [Errno 13] ...".
    assert response.status_code == 200, response.text
    assert response.json()["connected"] is True

    # Forensic logging degraded to the temp fallback instead of crashing.
    fallback_log = fallback_root / "cubos" / "logs" / "gantry" / "mill_control.log"
    assert fallback_log.exists()
