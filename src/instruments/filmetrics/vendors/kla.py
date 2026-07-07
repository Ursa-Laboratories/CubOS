import re
import subprocess
import threading
import time
from queue import Queue, Empty
from typing import Optional

from instruments.filmetrics.interface import FilmetricsInstrument
from instruments.filmetrics.exceptions import (
    FilmetricsConnectionError,
    FilmetricsCommandError,
    FilmetricsParseError,
)
from instruments.filmetrics.models import MeasurementResult

_SUCCESS_SENTINELS = ("complete", "successfully")
_ERROR_SENTINELS = ("error", "exception")

_DEFAULT_RESULT = MeasurementResult(thickness_nm=150.0, goodness_of_fit=0.95)


class KLAFilmetrics(FilmetricsInstrument):
    """Driver for the Filmetrics film thickness measurement system.

    Communicates with a C# console app (FilmetricsTool.exe) via stdin/stdout.
    Pass ``offline=True`` for dry runs — returns synthetic measurements.
    """

    def __init__(
        self,
        exe_path: str = "",
        recipe_name: str = "",
        command_timeout: float = 30.0,
        material_label: str = "Polyimide",
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        default_thickness_nm: float = 150.0,
        default_goodness_of_fit: float = 0.95,
        **kwargs,
    ):
        super().__init__(
            name=name, offset_x=offset_x, offset_y=offset_y,
            depth=depth,
            offline=offline,
        )
        self._exe_path = exe_path
        self._recipe_name = recipe_name
        self._command_timeout = command_timeout
        self._material_label = material_label
        self._default_result = MeasurementResult(
            thickness_nm=default_thickness_nm,
            goodness_of_fit=default_goodness_of_fit,
        )
        self._process: Optional[subprocess.Popen] = None

    # ── BaseInstrument interface ──────────────────────────────────────────

    def connect(self) -> None:
        if self._offline:
            self.logger.info("Filmetrics connected (offline)")
            return
        try:
            self._process = subprocess.Popen(
                [self._exe_path, self._recipe_name],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise FilmetricsConnectionError(
                f"Filmetrics exe not found: {self._exe_path}"
            ) from exc

        self._wait_for_init()
        self.logger.info("Connected to Filmetrics (pid=%s)", self._process.pid)

    def disconnect(self) -> None:
        if self._offline:
            self.logger.info("Filmetrics disconnected (offline)")
            return
        if self._process is None:
            return
        try:
            self._process.stdin.write("exit\n")
            self._process.stdin.flush()
        except OSError:
            pass
        finally:
            try:
                self._process.stdin.close()
                self._process.stdout.close()
            except OSError:
                pass
            try:
                self._process.wait(timeout=self._command_timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1.0)
            self.logger.info("Disconnected from Filmetrics")
            self._process = None

    def health_check(self) -> bool:
        if self._offline:
            return True
        return self._process is not None and self._process.poll() is None

    # ── Filmetrics-specific commands ──────────────────────────────────────

    def acquire_sample(self) -> None:
        if not self._offline:
            self._send_command("sample")

    def acquire_reference(self, reference_standard: str) -> None:
        if not self._offline:
            self._send_command(f"reference {reference_standard}")

    def acquire_background(self) -> None:
        if not self._offline:
            self._send_command("background")

    def commit_baseline(self) -> None:
        if not self._offline:
            self._send_command("commit")

    def measure(self) -> MeasurementResult:
        if self._offline:
            return self._default_result
        lines = self._send_command("measure")
        thickness_nm = self._parse_thickness(lines, material_label=self._material_label)
        if thickness_nm is None:
            raise FilmetricsParseError(
                f"No thickness line for material '{self._material_label}' "
                "in Filmetrics response."
            )
        return MeasurementResult(
            thickness_nm=thickness_nm,
            goodness_of_fit=self._parse_goodness_of_fit(lines),
        )

    def save_spectrum(self, identifier: str) -> None:
        if not self._offline:
            self._send_command(f"save {identifier}")

    # ── Private helpers ───────────────────────────────────────────────────

    def _wait_for_init(self) -> None:
        buffer = ""
        deadline = time.monotonic() + self._command_timeout
        while time.monotonic() < deadline:
            char = self._read_stdout_with_timeout(
                lambda: self._process.stdout.read(1),
                timeout=max(0.0, deadline - time.monotonic()),
                error_cls=FilmetricsConnectionError,
                description="init",
            )
            if not char:
                raise FilmetricsConnectionError("Process exited during init")
            buffer += char
            if "complete" in buffer.lower():
                return
        raise FilmetricsConnectionError("Timed out waiting for init")

    def _send_command(self, command: str) -> list[str]:
        if self._process is None or self._process.stdin is None:
            raise FilmetricsCommandError("Filmetrics process not connected")
        self._process.stdin.write(command + "\n")
        self._process.stdin.flush()

        lines: list[str] = []
        deadline = time.monotonic() + self._command_timeout
        while time.monotonic() < deadline:
            line = self._read_stdout_with_timeout(
                self._process.stdout.readline,
                timeout=max(0.0, deadline - time.monotonic()),
                error_cls=FilmetricsCommandError,
                description=f"response to '{command}'",
            )
            if not line:
                raise FilmetricsCommandError(
                    f"Process ended while waiting for response to '{command}'"
                )
            stripped = line.strip()
            lines.append(stripped)
            low = stripped.lower()
            if any(s in low for s in _SUCCESS_SENTINELS):
                return lines
            if any(s in low for s in _ERROR_SENTINELS):
                raise FilmetricsCommandError(
                    f"Command '{command}' failed: {stripped}"
                )

        raise FilmetricsCommandError(
            f"Timed out ({self._command_timeout}s) waiting for '{command}' to complete"
        )

    @staticmethod
    def _parse_thickness(
        lines: list[str],
        *,
        material_label: str = "Polyimide",
    ) -> Optional[float]:
        thickness = None
        for line in lines:
            if material_label in line:
                matches = re.findall(r"([-+]?\d*\.?\d+)\s*nm", line, re.IGNORECASE)
                if matches:
                    try:
                        thickness = float(matches[-1])
                    except ValueError:
                        pass
        return thickness

    def _read_stdout_with_timeout(
        self,
        read_func,
        *,
        timeout: float,
        error_cls,
        description: str,
    ):
        queue: Queue = Queue(maxsize=1)

        def run_read():
            try:
                queue.put((True, read_func()))
            except Exception as exc:
                queue.put((False, exc))

        thread = threading.Thread(target=run_read, daemon=True)
        thread.start()
        try:
            ok, value = queue.get(timeout=timeout)
        except Empty as exc:
            raise error_cls(
                f"Timed out ({self._command_timeout}s) waiting for Filmetrics {description}"
            ) from exc
        if ok:
            return value
        raise error_cls(f"Error reading Filmetrics {description}: {value}") from value

    @staticmethod
    def _parse_goodness_of_fit(lines: list[str]) -> Optional[float]:
        for line in lines:
            if "Goodness of fit" in line:
                match = re.search(r"[-+]?\d*\.?\d+|\d+", line)
                if match:
                    try:
                        return float(match.group())
                    except ValueError:
                        pass
        return None
