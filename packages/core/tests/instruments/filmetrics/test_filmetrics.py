import pytest
from unittest.mock import patch, MagicMock
import subprocess
import time

from cubos.instruments.base_instrument import BaseInstrument, InstrumentError
from cubos.instruments.filmetrics.models import MeasurementResult
from cubos.instruments.filmetrics.exceptions import (
    FilmetricsError,
    FilmetricsConnectionError,
    FilmetricsCommandError,
    FilmetricsParseError,
)
from cubos.instruments.filmetrics.vendors.kla import KLAFilmetrics


# --- MeasurementResult tests --------------------------------------------------

class TestMeasurementResult:

    def test_valid_measurement(self):
        result = MeasurementResult(thickness_nm=150.0, goodness_of_fit=0.95)
        assert result.thickness_nm == 150.0
        assert result.goodness_of_fit == 0.95
        assert result.is_valid is True

    def test_invalid_low_gof(self):
        result = MeasurementResult(thickness_nm=150.0, goodness_of_fit=0.3)
        assert result.is_valid is False

    def test_invalid_none_thickness(self):
        result = MeasurementResult(thickness_nm=None, goodness_of_fit=0.95)
        assert result.is_valid is False

    def test_invalid_none_gof(self):
        result = MeasurementResult(thickness_nm=150.0, goodness_of_fit=None)
        assert result.is_valid is False

    def test_boundary_gof_exactly_0_6(self):
        result = MeasurementResult(thickness_nm=100.0, goodness_of_fit=0.6)
        assert result.is_valid is True

    def test_boundary_gof_just_below_0_6(self):
        result = MeasurementResult(thickness_nm=100.0, goodness_of_fit=0.5999)
        assert result.is_valid is False

    def test_frozen_dataclass(self):
        result = MeasurementResult(thickness_nm=100.0, goodness_of_fit=0.9)
        with pytest.raises(AttributeError):
            result.thickness_nm = 200.0


# --- Exception hierarchy tests ------------------------------------------------

class TestExceptions:

    def test_filmetrics_error_is_instrument_error(self):
        assert issubclass(FilmetricsError, InstrumentError)

    def test_connection_error_hierarchy(self):
        assert issubclass(FilmetricsConnectionError, FilmetricsError)
        err = FilmetricsConnectionError("exe not found")
        assert isinstance(err, InstrumentError)

    def test_command_error_hierarchy(self):
        assert issubclass(FilmetricsCommandError, FilmetricsError)

    def test_parse_error_hierarchy(self):
        assert issubclass(FilmetricsParseError, FilmetricsError)


# --- Parsing tests ------------------------------------------------------------

class TestParsing:

    def test_parse_thickness_typical(self):
        lines = [
            "Measurement Results (System):",
            "Layer 1: Polyimide    150.23 nm",
            "Goodness of fit 0.98765",
            "Measurement Complete",
        ]
        assert KLAFilmetrics._parse_thickness(lines) == pytest.approx(150.23)

    def test_parse_thickness_negative(self):
        lines = ["Layer 1: Polyimide    -5.12 nm"]
        assert KLAFilmetrics._parse_thickness(lines) == pytest.approx(-5.12)

    def test_parse_thickness_no_match(self):
        lines = ["No relevant data here", "Measurement Complete"]
        assert KLAFilmetrics._parse_thickness(lines) is None

    def test_parse_thickness_custom_material_label(self):
        lines = ["Layer 1: Silicon Dioxide    88.4 nm"]
        assert KLAFilmetrics._parse_thickness(
            lines,
            material_label="Silicon Dioxide",
        ) == pytest.approx(88.4)

    def test_parse_thickness_multiple_polyimide_lines(self):
        """When multiple Polyimide lines exist, take the last nm value."""
        lines = [
            "Layer 1: Polyimide    100.0 nm",
            "Layer 2: Polyimide    200.0 nm",
        ]
        assert KLAFilmetrics._parse_thickness(lines) == pytest.approx(200.0)

    def test_parse_gof_typical(self):
        lines = [
            "Measurement Results (System):",
            "Layer 1: Polyimide    150.23 nm",
            "Goodness of fit 0.98765",
            "Measurement Complete",
        ]
        assert KLAFilmetrics._parse_goodness_of_fit(lines) == pytest.approx(0.98765)

    def test_parse_gof_integer(self):
        lines = ["Goodness of fit 1"]
        assert KLAFilmetrics._parse_goodness_of_fit(lines) == pytest.approx(1.0)

    def test_parse_gof_no_match(self):
        lines = ["No relevant data here"]
        assert KLAFilmetrics._parse_goodness_of_fit(lines) is None


# --- Driver lifecycle tests (mocked subprocess) -------------------------------

class TestFilmetricsLifecycle:

    def _make_mock_process(self, stdout_lines=None):
        """Create a mock Popen object that simulates the C# app.

        The C# app uses Console.Write (no newline) for init, so
        _wait_for_init reads char-by-char via read(1). We set up
        read() to return the init text one character at a time.
        """
        proc = MagicMock()
        proc.poll.return_value = None  # process is alive
        proc.pid = 12345

        # Init text read char-by-char (Console.Write, no newlines)
        init_text = "Initializing FIRemoteInitializition Complete"
        init_chars = [c for c in init_text]

        proc.stdout.read.side_effect = init_chars
        # readline is used by _send_command (post-init)
        if stdout_lines is not None:
            proc.stdout.readline.side_effect = [
                line + "\n" for line in stdout_lines
            ]
        proc.stdin = MagicMock()
        return proc

    @patch("subprocess.Popen")
    def test_connect_launches_subprocess(self, mock_popen):
        proc = self._make_mock_process()
        mock_popen.return_value = proc

        fm = KLAFilmetrics(exe_path="/fake/FilmetricsTool.exe", recipe_name="TestRecipe")
        fm.connect()

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert "/fake/FilmetricsTool.exe" in call_args[0][0]
        assert "TestRecipe" in call_args[0][0]

    @patch("subprocess.Popen")
    def test_connect_raises_on_missing_exe(self, mock_popen):
        mock_popen.side_effect = FileNotFoundError("not found")

        fm = KLAFilmetrics(exe_path="/bad/path.exe", recipe_name="Test")
        with pytest.raises(FilmetricsConnectionError):
            fm.connect()

    @patch("subprocess.Popen")
    def test_disconnect_sends_exit(self, mock_popen):
        proc = self._make_mock_process()
        mock_popen.return_value = proc

        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test")
        fm.connect()

        # Reset readline for disconnect's _send_command
        proc.stdout.readline.side_effect = ["Exiting...\n"]
        fm.disconnect()

        # Verify "exit" was written to stdin
        written_commands = [
            call[0][0] for call in proc.stdin.write.call_args_list
        ]
        assert any("exit" in cmd for cmd in written_commands)
        proc.wait.assert_called_once()

    @patch("subprocess.Popen")
    def test_disconnect_when_not_connected(self, mock_popen):
        """disconnect() should be safe to call when not connected."""
        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test")
        fm.disconnect()  # Should not raise

    @patch("subprocess.Popen")
    def test_health_check_true_when_alive(self, mock_popen):
        proc = self._make_mock_process()
        mock_popen.return_value = proc

        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test")
        fm.connect()
        proc.poll.return_value = None  # still alive
        assert fm.health_check() is True

    @patch("subprocess.Popen")
    def test_health_check_false_when_dead(self, mock_popen):
        proc = self._make_mock_process()
        mock_popen.return_value = proc

        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test")
        fm.connect()
        proc.poll.return_value = 1  # process exited
        assert fm.health_check() is False

    def test_health_check_false_when_not_connected(self):
        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test")
        assert fm.health_check() is False

    @patch("subprocess.Popen")
    def test_is_base_instrument(self, mock_popen):
        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test")
        assert isinstance(fm, BaseInstrument)


# --- Command method tests (mocked subprocess) ---------------------------------

class TestFilmetricsCommands:

    def _make_connected_filmetrics(self, mock_popen, command_response_lines):
        """Helper: create a connected KLAFilmetrics with mocked subprocess."""
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 12345
        proc.stdin = MagicMock()

        # Init uses read(1) char-by-char (Console.Write, no newline)
        init_text = "Initializing FIRemoteInitializition Complete"
        proc.stdout.read.side_effect = [c for c in init_text]

        # Commands use readline()
        command_lines = [line + "\n" for line in command_response_lines]
        proc.stdout.readline.side_effect = command_lines

        mock_popen.return_value = proc
        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test")
        fm.connect()
        return fm, proc

    @patch("subprocess.Popen")
    def test_acquire_sample(self, mock_popen):
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "Spectrum acquisition for sample completed successfully.",
        ])
        fm.acquire_sample()
        written = [c[0][0] for c in proc.stdin.write.call_args_list]
        assert any("sample" in cmd for cmd in written)

    @patch("subprocess.Popen")
    def test_acquire_reference(self, mock_popen):
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "The reference standard is: Si",
            "Acquiring reference spectrum...",
            "Reference spectrum acquired successfully.",
        ])
        fm.acquire_reference("Si")
        written = [c[0][0] for c in proc.stdin.write.call_args_list]
        assert any("reference Si" in cmd for cmd in written)

    @patch("subprocess.Popen")
    def test_acquire_background(self, mock_popen):
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "Acquiring background spectrum...",
            "Background spectrum acquired successfully.",
        ])
        fm.acquire_background()
        written = [c[0][0] for c in proc.stdin.write.call_args_list]
        assert any("background" in cmd for cmd in written)

    @patch("subprocess.Popen")
    def test_commit_baseline(self, mock_popen):
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "Baseline committed successfully.",
        ])
        fm.commit_baseline()
        written = [c[0][0] for c in proc.stdin.write.call_args_list]
        assert any("commit" in cmd for cmd in written)

    @patch("subprocess.Popen")
    def test_measure_returns_result(self, mock_popen):
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "Starting measurement...",
            "Measurement Results (System):",
            "Layer 1: Polyimide    150.23 nm",
            "Goodness of fit 0.98765",
            "Measurement Complete",
        ])
        result = fm.measure()
        assert isinstance(result, MeasurementResult)
        assert result.thickness_nm == pytest.approx(150.23)
        assert result.goodness_of_fit == pytest.approx(0.98765)
        assert result.is_valid is True

    @patch("subprocess.Popen")
    def test_measure_raises_parse_error_when_material_missing(self, mock_popen):
        fm, _ = self._make_connected_filmetrics(mock_popen, [
            "Starting measurement...",
            "Measurement Results (System):",
            "Layer 1: Silicon Dioxide    150.23 nm",
            "Goodness of fit 0.98765",
            "Measurement Complete",
        ])

        with pytest.raises(FilmetricsParseError, match="Polyimide"):
            fm.measure()

    @patch("subprocess.Popen")
    def test_measure_parses_configured_material_label(self, mock_popen):
        fm, _ = self._make_connected_filmetrics(mock_popen, [
            "Starting measurement...",
            "Measurement Results (System):",
            "Layer 1: Silicon Dioxide    150.23 nm",
            "Goodness of fit 0.98765",
            "Measurement Complete",
        ])
        fm._material_label = "Silicon Dioxide"

        assert fm.measure().thickness_nm == pytest.approx(150.23)

    @patch("subprocess.Popen")
    def test_measure_error_raises(self, mock_popen):
        """C# error responses should raise FilmetricsCommandError."""
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "Error: Invalid acquisition settings. Verify that a valid baseline has been established.",
        ])
        with pytest.raises(FilmetricsCommandError, match="Invalid acquisition settings"):
            fm.measure()

    @patch("subprocess.Popen")
    def test_exception_response_raises(self, mock_popen):
        """C# exception responses should also raise FilmetricsCommandError."""
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "General exception caught: something went wrong",
        ])
        with pytest.raises(FilmetricsCommandError, match="exception"):
            fm.acquire_sample()

    @patch("subprocess.Popen")
    def test_save_spectrum_placeholder(self, mock_popen):
        fm, proc = self._make_connected_filmetrics(mock_popen, [
            "Spectrum saved to: path successfully",
        ])
        fm.save_spectrum("A1")
        written = [c[0][0] for c in proc.stdin.write.call_args_list]
        assert any("save" in cmd for cmd in written)

    @patch("subprocess.Popen")
    def test_command_timeout(self, mock_popen):
        """If the subprocess never sends a completion sentinel, raise timeout."""
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 12345
        proc.stdin = MagicMock()

        # Init uses read(1) char-by-char
        init_text = "Initializing FIRemoteInitializition Complete"
        proc.stdout.read.side_effect = [c for c in init_text]
        # After init, readline returns EOF --- simulates no sentinel
        proc.stdout.readline.side_effect = [""]

        mock_popen.return_value = proc
        fm = KLAFilmetrics(exe_path="/fake/exe", recipe_name="Test", command_timeout=0.1)
        fm.connect()

        with pytest.raises(FilmetricsCommandError):
            fm.acquire_sample()

    def test_blocking_readline_times_out(self):
        proc = MagicMock()
        proc.stdin = MagicMock()

        def block_forever():
            time.sleep(10)
            return ""

        proc.stdout.readline.side_effect = block_forever
        fm = KLAFilmetrics(command_timeout=0.01)
        fm._process = proc

        start = time.monotonic()
        with pytest.raises(FilmetricsCommandError, match="Timed out"):
            fm.acquire_sample()
        assert time.monotonic() - start < 1.0


# --- Offline KLAFilmetrics tests -------------------------------------------------

class TestOfflineFilmetrics:

    def test_is_base_instrument(self):
        fm = KLAFilmetrics(offline=True)
        assert isinstance(fm, BaseInstrument)

    def test_connect_disconnect_cycle(self):
        fm = KLAFilmetrics(offline=True)
        fm.connect()
        assert fm.health_check() is True
        fm.disconnect()  # safe no-op in offline mode

    def test_measure_returns_default_result(self):
        fm = KLAFilmetrics(offline=True)
        fm.connect()
        result = fm.measure()
        assert isinstance(result, MeasurementResult)
        assert result.is_valid is True

    def test_measure_returns_custom_result(self):
        fm = KLAFilmetrics(
            offline=True,
            default_thickness_nm=42.0,
            default_goodness_of_fit=0.5,
        )
        fm.connect()
        result = fm.measure()
        assert result.thickness_nm == 42.0
        assert result.goodness_of_fit == 0.5
        assert result.is_valid is False

    def test_disconnect_safe_when_not_connected(self):
        fm = KLAFilmetrics(offline=True)
        fm.disconnect()  # Should not raise
