"""Smoke test: ``/api/v1/gantry/connect`` with a ``firmware: duet`` config.

Drives the real path — ``GantrySession`` -> ``Gantry`` -> ``DuetDriver`` —
over a fake RepRapFirmware serial device and asserts the endpoint connects.
This pins the firmware selector's full journey: YAML -> GantryYamlSchema ->
``model_dump`` dict -> session runtime config -> ``Gantry._create_driver``.

The fake serial is a self-contained port of ``FakeDuetSerial`` from
``packages/core`` ``tests.gantry.fake_serial`` (not importable here — only
``packages/core/src`` is on the test path), trimmed to the handshake this
test exercises: M115 identity, M409 object-model queries, and setup G-codes.
"""

from __future__ import annotations

import json
import re
from collections import deque

import serial.tools.list_ports

from cubos.gantry.gantry_driver import duet_driver as duet_module

from tests.api_client import api_request
from cubos_api.app import create_app
from cubos_api.config import get_settings
from cubos_api.routers import gantry as gantry_router
from cubos_api.services.yaml_io import write_yaml

VALID_DUET_GANTRY = {
    "serial_port": "/dev/fake-duet",
    "gantry_type": "cub_xl",
    "firmware": "duet",
    "cnc": {"factory_z_travel_mm": 110.0},
    "working_volume": {
        "x_min": 0.0, "x_max": 400.0,
        "y_min": 0.0, "y_max": 300.0,
        "z_min": 0.0, "z_max": 110.0,
    },
    "instruments": {},
}

_FAKE_RRF_M115 = (
    "FIRMWARE_NAME: RepRapFirmware for Duet 3 MB6XD "
    "FIRMWARE_VERSION: 3.6.1 ELECTRONICS: Duet 3 MB6XD v1.02 or later"
)


class FakeDuetSerial:
    """Minimal scriptable pyserial double speaking RRF's USB line protocol."""

    instances: list["FakeDuetSerial"] = []

    def __init__(self, *args, **kwargs):
        self.port = kwargs.get("port", "/dev/fake-duet")
        self.timeout = kwargs.get("timeout", 2)
        self.is_open = True
        self.status = "idle"
        self.position = [0.0, 0.0, 0.0]
        self.writes: list[bytes] = []
        self._rx: deque[bytes] = deque()
        FakeDuetSerial.instances.append(self)

    @property
    def in_waiting(self) -> int:
        return sum(len(item) for item in self._rx)

    def _queue_line(self, value: str) -> None:
        self._rx.append(f"{value}\r\n".encode("ascii"))

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        command = data.decode("ascii", errors="ignore").strip()
        if not command:
            return len(data)
        if command == "M115":
            self._queue_line(_FAKE_RRF_M115)
            self._queue_line("ok")
        elif command.startswith("M409"):
            match = re.search(r'K"([^"]+)"', command)
            key = match.group(1) if match else ""
            if key == "state.status":
                result: object = self.status
            elif key == "move.axes":
                letters = ("X", "Y", "Z")
                result = [
                    {
                        "letter": letters[i],
                        "homed": False,
                        "machinePosition": self.position[i],
                        "userPosition": self.position[i],
                    }
                    for i in range(3)
                ]
            else:
                result = None
            self._queue_line(json.dumps({"key": key, "flags": "", "result": result}))
            self._queue_line("ok")
        else:
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
        return self._rx.popleft()

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


def test_connect_selects_duet_driver_and_succeeds(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    gantry_dir = config_dir / "gantry"
    gantry_dir.mkdir(parents=True)
    write_yaml(gantry_dir / "duet.yaml", VALID_DUET_GANTRY)
    monkeypatch.setattr(get_settings(), "config_dir", config_dir)

    # Fresh module-level session so /connect builds a real GantrySession.
    monkeypatch.setattr(gantry_router, "_session", None)

    # Fake RRF serial device; no real sleeps or port scanning.
    FakeDuetSerial.instances.clear()
    monkeypatch.setattr(duet_module.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(duet_module.serial, "Serial", FakeDuetSerial)
    monkeypatch.setattr(
        serial.tools.list_ports, "grep", lambda *_a, **_k: iter(())
    )

    response = api_request(
        create_app(),
        "POST",
        "/api/v1/gantry/connect",
        json={"filename": "duet.yaml"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["connected"] is True

    # The RRF protocol — not GRBL — actually ran on the wire.
    assert FakeDuetSerial.instances, "DuetDriver never opened the fake port"
    all_writes = b"".join(
        w for fake in FakeDuetSerial.instances for w in fake.writes
    )
    assert b"M115" in all_writes
    assert b"M409" in all_writes
    assert b"$$" not in all_writes
