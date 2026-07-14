"""Small fake pyserial GRBL double for driver tests."""

from __future__ import annotations

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
