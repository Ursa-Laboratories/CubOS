"""Small fake pyserial doubles (GRBL and Duet/RepRapFirmware) for driver tests."""

from __future__ import annotations

import json
import re
from collections import deque


class FakeGrblSerial:
    """Scriptable serial double with GRBL-style command responses."""

    def __init__(
        self,
        *,
        port: str = "/dev/fake-grbl",
        timeout: float | None = 2,
        is_open: bool = True,
        status: str = "<Idle|WPos:0.000,0.000,0.000|WCO:0.000,0.000,0.000|FS:0,0>",
        settings: dict[str, str] | None = None,
        chunks: list[bytes | str] | None = None,
        jog_response: str = "ok",
    ):
        self.port = port
        self.timeout = timeout
        self.is_open = is_open
        self.status = status
        self.settings = settings or {"$10": "0", "$20": "1", "$130": "400.000"}
        self.jog_response = jog_response
        self.writes: list[bytes] = []
        self._rx: deque[bytes] = deque()
        for chunk in chunks or []:
            self.queue(chunk)

    @property
    def in_waiting(self) -> int:
        return sum(len(item) for item in self._rx)

    def queue(self, value: bytes | str) -> None:
        if isinstance(value, str):
            value = value.encode("ascii")
        self._rx.append(value)

    def queue_line(self, value: str) -> None:
        self.queue(value if value.endswith("\r\n") else f"{value}\r\n")

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"?":
            self.queue_line(self.status)
        elif data == b"!":
            self.status = "<Hold:0|WPos:0.000,0.000,0.000|FS:0,0>"
        elif data == b"~":
            self.status = "<Run|WPos:0.000,0.000,0.000|FS:0,0>"
        elif data == b"\x85":
            self.status = "<Idle|WPos:0.000,0.000,0.000|FS:0,0>"
        elif data == b"\x18":
            self.queue_line("Grbl 1.1h ['$' for help]")
        else:
            command = data.decode("ascii", errors="ignore").strip()
            if command == "$$":
                for key, value in self.settings.items():
                    self.queue_line(f"{key}={value}")
                self.queue_line("ok")
            elif command == "$N":
                self.queue_line("$N0=")
                self.queue_line("$N1=")
                self.queue_line("ok")
            elif command == "$H":
                self.status = "<Run|WPos:0.000,0.000,0.000|FS:0,0>"
                self.queue_line("ok")
            elif command == "$X":
                self.status = "<Idle|WPos:0.000,0.000,0.000|FS:0,0>"
                self.queue_line("ok")
            elif command.startswith("$J="):
                self.queue_line(self.jog_response)
            elif command:
                self.queue_line("ok")
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
            if data.endswith(b"\r\n"):
                break
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


_FAKE_RRF_M115 = (
    "FIRMWARE_NAME: RepRapFirmware for Duet 3 MB6XD "
    "FIRMWARE_VERSION: 3.6.1 ELECTRONICS: Duet 3 MB6XD v1.02 or later"
)

_AXIS_WORD_RE = re.compile(r"([XYZF])(-?\d+(?:\.\d+)?)")


class FakeDuetSerial:
    """Scriptable serial double speaking RepRapFirmware's USB line protocol.

    Models the subset DuetDriver relies on: M115 identity, M409
    object-model queries (state.status / move.axes), buffered G1 moves
    with G90/G91 modality, G28 homing, M112 emergency halt, and M999
    reset. Every reply is terminated by an ``ok`` line, as on real RRF.

    ``moves_to_idle_after`` simulates motion: after a G1/G28 the status
    reads ``processing`` for that many state queries before settling to
    ``idle`` (0 = instantly idle).
    """

    def __init__(
        self,
        *,
        port: str = "/dev/fake-duet",
        timeout: float | None = 2,
        is_open: bool = True,
        status: str = "idle",
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        homed: bool = False,
        homed_position: tuple[float, float, float] = (400.0, 300.0, 110.0),
        moves_to_idle_after: int = 0,
        move_error: str | None = None,
        identity: str = _FAKE_RRF_M115,
    ):
        self.port = port
        self.timeout = timeout
        self.is_open = is_open
        self.status = status
        self.position = list(position)
        self.homed = [homed, homed, homed]
        self.homed_position = homed_position
        self.moves_to_idle_after = moves_to_idle_after
        self._busy_polls_left = 0
        self.move_error = move_error
        self.identity = identity
        self.relative_mode = False
        self.writes: list[bytes] = []
        self._rx: deque[bytes] = deque()

    # -- pyserial surface ------------------------------------------------

    @property
    def in_waiting(self) -> int:
        return sum(len(item) for item in self._rx)

    def queue_line(self, value: str) -> None:
        self._rx.append(f"{value}\r\n".encode("ascii"))

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

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

    # -- RRF behavior ----------------------------------------------------

    def _current_status(self) -> str:
        if self._busy_polls_left > 0:
            self._busy_polls_left -= 1
            return "processing"
        return self.status

    def _axes_payload(self) -> list[dict]:
        letters = ("X", "Y", "Z")
        return [
            {
                "letter": letters[i],
                "homed": self.homed[i],
                "machinePosition": self.position[i],
                "userPosition": self.position[i],
            }
            for i in range(3)
        ]

    def _apply_move(self, command: str) -> None:
        words = dict(_AXIS_WORD_RE.findall(command.upper()))
        axis_index = {"X": 0, "Y": 1, "Z": 2}
        for letter, index in axis_index.items():
            if letter in words:
                value = float(words[letter])
                if self.relative_mode:
                    self.position[index] += value
                else:
                    self.position[index] = value
        if any(letter in words for letter in axis_index):
            self._busy_polls_left = self.moves_to_idle_after

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        command = data.decode("ascii", errors="ignore").strip()
        if not command:
            return len(data)

        if self.status == "halted" and command not in ("M999", "M115") and not command.startswith("M409"):
            self.queue_line(f"Error: {command.split()[0]}: Machine is halted")
            self.queue_line("ok")
            return len(data)

        if command == "M115":
            self.queue_line(self.identity)
            self.queue_line("ok")
        elif command.startswith("M409"):
            self._reply_object_model(command)
        elif command == "G28" or command.startswith("G28 "):
            self.homed = [True, True, True]
            self.position = list(self.homed_position)
            self._busy_polls_left = self.moves_to_idle_after
            self.queue_line("ok")
        elif command == "G90":
            self.relative_mode = False
            self.queue_line("ok")
        elif command == "G91":
            self.relative_mode = True
            self.queue_line("ok")
        elif command.startswith(("G1", "G01", "G0 ", "G00")):
            if self.move_error:
                self.queue_line(self.move_error)
                self.queue_line("ok")
            else:
                self._apply_move(command)
                self.queue_line("ok")
        elif command == "M112":
            self.status = "halted"
            self.homed = [False, False, False]
            self.queue_line("Emergency Stop! Reset the controller to continue.")
        elif command == "M999":
            self.status = "idle"
            self.homed = [False, False, False]
            self._busy_polls_left = 0
            # Real boards drop USB here; the driver closes and reopens the
            # port, which this double tolerates via open()/close().
        else:
            self.queue_line("ok")
        return len(data)

    def _reply_object_model(self, command: str) -> None:
        match = re.search(r'K"([^"]+)"', command)
        key = match.group(1) if match else ""
        if key == "state.status":
            result: object = self._current_status()
        elif key == "move.axes":
            result = self._axes_payload()
        elif key == "move.limitAxes":
            result = True
        else:
            result = None
        self.queue_line(json.dumps({"key": key, "flags": "", "result": result}))
        self.queue_line("ok")
