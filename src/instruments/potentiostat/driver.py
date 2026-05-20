"""Admiral Instruments SquidStat potentiostat driver.

Wraps the vendor ``SquidstatPyLibrary`` Qt (PySide6) API in a blocking,
synchronous facade that matches the rest of the CubOS instruments stack.

Qt integration strategy (see plan for rationale):
  * A single process-wide ``QCoreApplication`` is created lazily on
    :meth:`connect` and reused for the lifetime of the process. If the host
    already owns one (e.g. a GUI or ``pytest-qt``), we attach to it via
    ``QCoreApplication.instance()`` instead of creating a second.
  * Each experiment uses a fresh local ``QEventLoop`` that blocks until the
    vendor emits ``experimentStopped`` (or a hard timeout fires).

The vendor SDK is imported lazily inside :meth:`connect`; the package can be
imported, params/results built, and :attr:`offline` runs performed without it.

Result shape follows the ``UVVisSpectrum`` precedent: ``tuple[float, ...]``
traces, technique-specific scalar fields surfaced at the top level, and a
free-form ``metadata`` mapping for run-level annotations.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

from instruments.base_instrument import BaseInstrument
from instruments.potentiostat.exceptions import (
    PotentiostatCommandError,
    PotentiostatConfigError,
    PotentiostatConnectionError,
    PotentiostatTimeoutError,
)
from instruments.potentiostat.models import (
    CAParams,
    CAResult,
    CPParams,
    CPResult,
    CVParams,
    CVResult,
    OCPParams,
    OCPResult,
)


_VENDOR = "admiral"


class Potentiostat(BaseInstrument):
    """Driver for Admiral Instruments SquidStat potentiostats.

    Parameters
    ----------
    port:
        COM port / serial device identifier to hand to
        ``AisDeviceTracker.connectToDeviceOnComPort``.
    channel:
        Channel index on multi-channel devices. Single-channel SquidStats use 0.
    command_timeout:
        Hard upper bound (seconds) on any single experiment. Defaults to 10 min.
    offline:
        When True, hardware calls are replaced with deterministic synthetic
        traces. Useful for dry-running protocols without a device attached.
    """

    vendor: str = _VENDOR

    def __init__(
        self,
        port: str = "",
        channel: int = 0,
        command_timeout: float = 600.0,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        **kwargs: Any,
    ):
        super().__init__(
            name=name,
            offset_x=offset_x,
            offset_y=offset_y,
            depth=depth,
            offline=offline,
        )
        if channel < 0:
            raise PotentiostatConfigError(
                f"channel must be >= 0, got {channel}"
            )
        self._port = port
        self._channel = channel
        self._command_timeout = command_timeout

        # Populated by connect() when online.
        self._qt: Optional[_QtBindings] = None
        self._tracker: Optional[Any] = None
        self._handler: Optional[Any] = None
        self._device_id: Optional[str] = None

        # Fixed-seed RNG (seed=0) for reproducible offline synthesis.
        # Shared stdlib Random so offline results are stable across runs of
        # a freshly-constructed driver.
        self._offline_rng = random.Random(0)

    # ── BaseInstrument interface ──────────────────────────────────────────

    def connect(self) -> None:
        if self._offline:
            self.logger.info("Potentiostat connected (offline)")
            return

        self._qt = _load_qt_bindings()
        self._qt.ensure_application()

        try:
            tracker = self._qt.AisDeviceTracker.Instance()
        except Exception as exc:  # vendor SDK raises varied types
            raise PotentiostatConnectionError(
                f"Failed to acquire AisDeviceTracker singleton: {exc}"
            ) from exc

        loop = self._qt.QEventLoop()
        captured: dict[str, Any] = {}

        def _on_device_connected(device_name: str) -> None:
            captured["device_name"] = device_name
            captured["handler"] = tracker.getInstrumentHandler(device_name)
            loop.quit()

        tracker.newDeviceConnected.connect(_on_device_connected)
        self._qt.QTimer.singleShot(
            int(self._command_timeout * 1000), loop.quit
        )

        try:
            tracker.connectToDeviceOnComPort(self._port)
        except Exception as exc:
            tracker.newDeviceConnected.disconnect(_on_device_connected)
            raise PotentiostatConnectionError(
                f"connectToDeviceOnComPort('{self._port}') failed: {exc}"
            ) from exc

        loop.exec()

        # Best-effort cleanup of the one-shot connect slot. A late disconnect
        # can raise if the underlying Qt object is already gone (device
        # yanked mid-handshake) — logged, never swallowed silently.
        try:
            tracker.newDeviceConnected.disconnect(_on_device_connected)
        except (RuntimeError, TypeError) as exc:
            self.logger.warning(
                "newDeviceConnected.disconnect during connect cleanup: %s", exc
            )

        if "handler" not in captured or captured["handler"] is None:
            raise PotentiostatConnectionError(
                f"No SquidStat device appeared on port '{self._port}' "
                f"within {self._command_timeout}s"
            )

        self._tracker = tracker
        self._handler = captured["handler"]
        self._device_id = captured.get("device_name")
        self.logger.info(
            "Connected to SquidStat '%s' on %s (channel %d)",
            self._device_id, self._port, self._channel,
        )

    def disconnect(self) -> None:
        if self._offline:
            self.logger.info("Potentiostat disconnected (offline)")
            return
        if self._tracker is not None and self._device_id is not None:
            try:
                self._tracker.disconnectFromDevice(self._device_id)
            except Exception as exc:
                self.logger.warning(
                    "disconnectFromDevice raised: %s", exc
                )
        self._handler = None
        self._tracker = None
        self._device_id = None
        self.logger.info("Disconnected from potentiostat")

    def health_check(self) -> bool:
        if self._offline:
            return True
        return self._handler is not None

    # ── Experiment methods ────────────────────────────────────────────────

    def run_cv(self, params: CVParams) -> CVResult:
        if self._offline:
            return self._offline_cv(params)
        element_factory = lambda mod: mod.AisCyclicVoltammetryElement(
            params.start_V, params.vertex1_V, params.vertex2_V,
            params.end_V, params.scan_rate_V_per_s,
            params.sampling_interval_s,
        )
        time_buf: List[float] = []
        voltage_buf: List[float] = []
        current_buf: List[float] = []
        meta = self._run_experiment(
            element_factory,
            cycles=params.cycles,
            dc_sink=lambda sample: (
                time_buf.append(float(sample.timestamp)),
                voltage_buf.append(float(sample.workingElectrodeVoltage)),
                current_buf.append(float(sample.current)),
            ),
        )
        return CVResult(
            time_s=tuple(time_buf),
            voltage_v=tuple(voltage_buf),
            current_a=tuple(current_buf),
            scan_rate_v_s=params.scan_rate_V_per_s,
            step_size_v=params.scan_rate_V_per_s * params.sampling_interval_s,
            cycles=params.cycles,
            vendor=self.vendor,
            metadata=meta,
        )

    def run_ocp(self, params: OCPParams) -> OCPResult:
        if self._offline:
            return self._offline_ocp(params)
        element_factory = lambda mod: mod.AisOpenCircuitElement(
            params.duration_s, params.sampling_interval_s,
        )
        time_buf: List[float] = []
        voltage_buf: List[float] = []
        meta = self._run_experiment(
            element_factory,
            cycles=1,
            dc_sink=lambda sample: (
                time_buf.append(float(sample.timestamp)),
                voltage_buf.append(float(sample.workingElectrodeVoltage)),
            ),
        )
        return OCPResult(
            time_s=tuple(time_buf),
            voltage_v=tuple(voltage_buf),
            sample_period_s=params.sampling_interval_s,
            duration_s=params.duration_s,
            vendor=self.vendor,
            metadata=meta,
        )

    def run_ca(self, params: CAParams) -> CAResult:
        if self._offline:
            return self._offline_ca(params)
        element_factory = lambda mod: mod.AisConstantPotElement(
            params.potential_V, params.sampling_interval_s, params.duration_s,
        )
        time_buf: List[float] = []
        voltage_buf: List[float] = []
        current_buf: List[float] = []
        meta = self._run_experiment(
            element_factory,
            cycles=1,
            dc_sink=lambda sample: (
                time_buf.append(float(sample.timestamp)),
                voltage_buf.append(float(sample.workingElectrodeVoltage)),
                current_buf.append(float(sample.current)),
            ),
        )
        return CAResult(
            time_s=tuple(time_buf),
            voltage_v=tuple(voltage_buf),
            current_a=tuple(current_buf),
            sample_period_s=params.sampling_interval_s,
            duration_s=params.duration_s,
            step_potential_v=params.potential_V,
            vendor=self.vendor,
            metadata=meta,
        )

    def run_cp(self, params: CPParams) -> CPResult:
        if self._offline:
            return self._offline_cp(params)
        element_factory = lambda mod: mod.AisConstantCurrentElement(
            params.current_A, params.sampling_interval_s, params.duration_s,
        )
        time_buf: List[float] = []
        voltage_buf: List[float] = []
        current_buf: List[float] = []
        meta = self._run_experiment(
            element_factory,
            cycles=1,
            dc_sink=lambda sample: (
                time_buf.append(float(sample.timestamp)),
                voltage_buf.append(float(sample.workingElectrodeVoltage)),
                current_buf.append(float(sample.current)),
            ),
        )
        return CPResult(
            time_s=tuple(time_buf),
            voltage_v=tuple(voltage_buf),
            current_a=tuple(current_buf),
            sample_period_s=params.sampling_interval_s,
            duration_s=params.duration_s,
            step_current_a=params.current_A,
            vendor=self.vendor,
            metadata=meta,
        )

    # ── Shared online experiment plumbing ─────────────────────────────────

    def _run_experiment(
        self,
        element_factory: Callable[[Any], Any],
        *,
        cycles: int,
        dc_sink: Callable[[Any], None],
    ) -> dict[str, Any]:
        """Run one experiment to completion, collecting DC samples.

        ``element_factory(mod)`` builds the SquidstatPyLibrary experiment
        element from the vendor module. ``dc_sink`` receives each DC sample
        as it arrives.
        """
        if self._handler is None or self._qt is None:
            raise PotentiostatCommandError(
                "Potentiostat is not connected; call connect() first."
            )

        qt = self._qt
        mod = qt.squidstat
        experiment = mod.AisExperiment()
        element = element_factory(mod)
        try:
            experiment.appendElement(element, cycles)
        except Exception as exc:
            raise PotentiostatCommandError(
                f"Failed to append experiment element: {exc}"
            ) from exc

        loop = qt.QEventLoop()
        started_at = datetime.now(timezone.utc)
        stopped_reason: dict[str, Any] = {}

        def _on_dc(_channel: int, sample: Any) -> None:
            dc_sink(sample)

        def _on_stopped(_channel: int, reason: Any) -> None:
            stopped_reason["reason"] = reason
            loop.quit()

        self._handler.activeDCDataReady.connect(_on_dc)
        self._handler.experimentStopped.connect(_on_stopped)

        timeout_flag = {"fired": False}

        def _on_timeout() -> None:
            timeout_flag["fired"] = True
            loop.quit()

        qt.QTimer.singleShot(
            int(self._command_timeout * 1000), _on_timeout
        )

        try:
            err = self._handler.uploadExperimentToChannel(
                self._channel, experiment
            )
            # Vendor returns an error code / string truthy on failure.
            if err:
                raise PotentiostatCommandError(
                    f"uploadExperimentToChannel failed: {err}"
                )
            err = self._handler.startUploadedExperiment(self._channel)
            if err:
                raise PotentiostatCommandError(
                    f"startUploadedExperiment failed: {err}"
                )

            loop.exec()
        finally:
            # Signal disconnect is best-effort: PySide6 can raise RuntimeError
            # when the underlying C++ object is gone (device disconnected mid-
            # run) or TypeError if the slot was never actually connected.
            # Either is worth logging so slot-leak regressions are visible.
            for signal_name, signal, slot in (
                ("activeDCDataReady", self._handler.activeDCDataReady, _on_dc),
                ("experimentStopped", self._handler.experimentStopped, _on_stopped),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError) as exc:
                    self.logger.warning(
                        "%s.disconnect during experiment cleanup: %s",
                        signal_name, exc,
                    )

        aborted = timeout_flag["fired"] and "reason" not in stopped_reason
        if aborted:
            try:
                self._handler.stopExperiment(self._channel)
            except Exception as exc:
                self.logger.warning(
                    "stopExperiment after timeout raised: %s", exc
                )
            raise PotentiostatTimeoutError(
                f"Experiment exceeded {self._command_timeout}s timeout"
            )

        stopped_at = datetime.now(timezone.utc)
        return {
            "device_id": self._device_id,
            "channel": self._channel,
            "started_at": started_at.isoformat(),
            "stopped_at": stopped_at.isoformat(),
            "aborted": False,
            "stop_reason": stopped_reason.get("reason"),
        }

    # ── Offline synthesis ─────────────────────────────────────────────────
    #
    # Uses stdlib ``math`` + ``random`` so the driver (and therefore the
    # package) can be imported without numpy. Trace sizes here are small
    # (seconds of data at 10-100 ms sampling), so list/tuple math is
    # perfectly adequate — the numpy dependency would only be justified for
    # large-N matrix operations that don't happen in synthetic data.

    def _offline_cv(self, params: CVParams) -> CVResult:
        # One full cycle: start → v1 → v2 → end. Span is distance traversed.
        span = (
            abs(params.vertex1_V - params.start_V)
            + abs(params.vertex2_V - params.vertex1_V)
            + abs(params.end_V - params.vertex2_V)
        )
        cycle_duration = span / params.scan_rate_V_per_s
        per_cycle = max(
            int(math.ceil(cycle_duration / params.sampling_interval_s)), 2
        )

        voltage: List[float] = []
        time: List[float] = []
        for c in range(params.cycles):
            sweep = self._triangular_sweep(
                params.start_V, params.vertex1_V,
                params.vertex2_V, params.end_V, per_cycle,
            )
            voltage.extend(sweep)
            offset = c * cycle_duration
            time.extend(
                offset + i * cycle_duration / per_cycle
                for i in range(per_cycle)
            )

        # Simple Butler-Volmer-ish synthetic current: scaled sinh around 0V.
        current = [
            1e-6 * math.sinh(v / 0.05) + self._offline_rng.gauss(0.0, 5e-9)
            for v in voltage
        ]

        return CVResult(
            time_s=tuple(time),
            voltage_v=tuple(voltage),
            current_a=tuple(current),
            scan_rate_v_s=params.scan_rate_V_per_s,
            step_size_v=params.scan_rate_V_per_s * params.sampling_interval_s,
            cycles=params.cycles,
            vendor=self.vendor,
            metadata=self._offline_metadata(aborted=False),
        )

    def _offline_ocp(self, params: OCPParams) -> OCPResult:
        n = max(
            int(math.ceil(params.duration_s / params.sampling_interval_s)), 1
        )
        time = tuple(i * params.duration_s / n for i in range(n))
        # Slow exponential settle toward a stable OCV of ~0.35 V.
        decay = max(params.duration_s / 4.0, 1e-6)
        voltage = tuple(
            0.35 + 0.05 * math.exp(-t / decay)
            + self._offline_rng.gauss(0.0, 1e-4)
            for t in time
        )
        return OCPResult(
            time_s=time,
            voltage_v=voltage,
            sample_period_s=params.sampling_interval_s,
            duration_s=params.duration_s,
            vendor=self.vendor,
            metadata=self._offline_metadata(aborted=False),
        )

    def _offline_ca(self, params: CAParams) -> CAResult:
        n = max(
            int(math.ceil(params.duration_s / params.sampling_interval_s)), 1
        )
        time = tuple(i * params.duration_s / n for i in range(n))
        # Cottrell-like t^-1/2 decay, clipped near t=0.
        current = tuple(
            1e-5 / math.sqrt(max(t, params.sampling_interval_s))
            + self._offline_rng.gauss(0.0, 1e-8)
            for t in time
        )
        voltage = tuple(params.potential_V for _ in range(n))
        return CAResult(
            time_s=time,
            voltage_v=voltage,
            current_a=current,
            sample_period_s=params.sampling_interval_s,
            duration_s=params.duration_s,
            step_potential_v=params.potential_V,
            vendor=self.vendor,
            metadata=self._offline_metadata(aborted=False),
        )

    def _offline_cp(self, params: CPParams) -> CPResult:
        n = max(
            int(math.ceil(params.duration_s / params.sampling_interval_s)), 1
        )
        time = tuple(i * params.duration_s / n for i in range(n))
        current = tuple(params.current_A for _ in range(n))
        # Faradaic-ish drift on the working electrode potential.
        voltage = tuple(
            0.1 + 0.002 * t + self._offline_rng.gauss(0.0, 1e-4)
            for t in time
        )
        return CPResult(
            time_s=time,
            voltage_v=voltage,
            current_a=current,
            sample_period_s=params.sampling_interval_s,
            duration_s=params.duration_s,
            step_current_a=params.current_A,
            vendor=self.vendor,
            metadata=self._offline_metadata(aborted=False),
        )

    @staticmethod
    def _triangular_sweep(
        start: float, v1: float, v2: float, end: float, n: int,
    ) -> List[float]:
        """Distribute ``n`` samples across three linear legs weighted by span.

        Legs are endpoint-exclusive except the final one, which closes the
        sweep at ``end``. Returned list is exactly ``n`` long.
        """
        legs = [(start, v1), (v1, v2), (v2, end)]
        lengths = [abs(b - a) for a, b in legs]
        total = sum(lengths) or 1.0
        counts = [max(int(round(n * (L / total))), 1) for L in lengths]
        # Adjust final leg so the total is exactly n, clamping to at least 1.
        counts[-1] = max(n - (counts[0] + counts[1]), 1)

        result: List[float] = []
        for i, ((a, b), c) in enumerate(zip(legs, counts)):
            if i < 2:
                # endpoint-exclusive leg
                result.extend(a + (b - a) * k / c for k in range(c))
            else:
                # endpoint-inclusive final leg
                if c == 1:
                    result.append(b)
                else:
                    result.extend(a + (b - a) * k / (c - 1) for k in range(c))
        return result[:n]

    def _offline_metadata(self, *, aborted: bool) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "device_id": "offline",
            "channel": self._channel,
            "started_at": now,
            "stopped_at": now,
            "aborted": aborted,
            "stop_reason": None,
        }


# ── Lazy vendor SDK loader ───────────────────────────────────────────────────


class _QtBindings:
    """Bundle of vendor/Qt symbols resolved at connect() time."""

    def __init__(
        self,
        squidstat: Any,
        QCoreApplication: Any,
        QEventLoop: Any,
        QTimer: Any,
    ):
        self.squidstat = squidstat
        self.QCoreApplication = QCoreApplication
        self.QEventLoop = QEventLoop
        self.QTimer = QTimer
        self.AisDeviceTracker = squidstat.AisDeviceTracker

    def ensure_application(self) -> Any:
        app = self.QCoreApplication.instance()
        if app is None:
            app = self.QCoreApplication([])
        return app


def _load_qt_bindings() -> _QtBindings:
    """Lazy-import SquidstatPyLibrary + PySide6.

    Raises :class:`PotentiostatConnectionError` with an actionable install
    hint if either dependency is unavailable.
    """
    try:
        import SquidstatPyLibrary as squidstat  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PotentiostatConnectionError(
            "SquidstatPyLibrary is not installed. "
            "Install with: pip install 'cubos[potentiostat]'"
        ) from exc

    try:
        from PySide6.QtCore import (  # type: ignore[import-not-found]
            QCoreApplication, QEventLoop, QTimer,
        )
    except ImportError as exc:
        raise PotentiostatConnectionError(
            "PySide6 is not installed (required by SquidstatPyLibrary). "
            "Install with: pip install 'cubos[potentiostat]'"
        ) from exc

    return _QtBindings(
        squidstat=squidstat,
        QCoreApplication=QCoreApplication,
        QEventLoop=QEventLoop,
        QTimer=QTimer,
    )
