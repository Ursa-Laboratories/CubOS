import ctypes as C
import time
from typing import Optional

from instruments.base_instrument import BaseInstrument
from instruments.uvvis_ccs.exceptions import (
    UVVisCCSConnectionError,
    UVVisCCSMeasurementError,
    UVVisCCSTimeoutError,
)
from instruments.uvvis_ccs.models import NUM_PIXELS, UVVisSpectrum

_STATUS_IDLE = 0x0002
_STATUS_SCAN_READY = 0x0010
_IDLE_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05


def _synthetic_spectrum(integration_time_s: float = 0.24) -> UVVisSpectrum:
    """Generate a flat synthetic spectrum for offline mode."""
    step = 600.0 / (NUM_PIXELS - 1)
    wavelengths = tuple(200.0 + i * step for i in range(NUM_PIXELS))
    intensities = tuple(0.5 for _ in range(NUM_PIXELS))
    return UVVisSpectrum(
        wavelengths=wavelengths,
        intensities=intensities,
        integration_time_s=integration_time_s,
    )


class UVVisCCS(BaseInstrument):
    """Driver for the Thorlabs CCS-series compact spectrometer.

    Communicates via the Thorlabs TLCCS DLL (ctypes).
    Pass ``offline=True`` for dry runs — returns synthetic spectra.
    """

    def __init__(
        self,
        serial_number: str = "",
        dll_path: str = "TLCCS_64.dll",
        default_integration_time_s: float = 0.24,
        name: Optional[str] = None,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        depth: float = 0.0,
        offline: bool = False,
        **kwargs,
    ):
        super().__init__(
            name=name, offset_x=offset_x, offset_y=offset_y,
            depth=depth,
            offline=offline,
        )
        self._serial_number = serial_number
        self._dll_path = dll_path
        self._default_integration_time_s = default_integration_time_s
        self._integration_time_s = default_integration_time_s
        self._dll = None
        self._handle: Optional[C.c_uint32] = None
        self._wavelengths: Optional[tuple[float, ...]] = None

    # ── BaseInstrument interface ──────────────────────────────────────────

    def connect(self) -> None:
        if self._offline:
            self.logger.info("UVVisCCS connected (offline)")
            return
        try:
            self._dll = C.cdll.LoadLibrary(self._dll_path)
        except OSError as exc:
            raise UVVisCCSConnectionError(
                f"Failed to load DLL: {self._dll_path}"
            ) from exc

        self._configure_dll_prototypes()

        resource = (
            f"USB0::0x1313::0x8081::{self._serial_number}::RAW"
        ).encode("ascii")
        self._handle = C.c_uint32()

        rc = self._dll.tlccs_init(
            resource, True, True, C.byref(self._handle)
        )
        if rc != 0:
            raise UVVisCCSConnectionError(
                f"tlccs_init failed with code {rc} for serial {self._serial_number}"
            )

        self._load_wavelength_data()
        self.set_integration_time(self._default_integration_time_s)
        self.logger.info(
            "Connected to CCS spectrometer (serial=%s)", self._serial_number
        )

    def disconnect(self) -> None:
        if self._offline:
            self.logger.info("UVVisCCS disconnected (offline)")
            return
        if self._handle is None:
            return
        try:
            self._dll.tlccs_close(self._handle)
        except OSError:
            pass
        finally:
            self.logger.info("Disconnected from CCS spectrometer")
            self._handle = None

    def health_check(self) -> bool:
        if self._offline:
            return True
        if self._handle is None:
            return False
        try:
            self._get_status()
            return True
        except Exception:
            return False

    # ── UVVis-specific commands ───────────────────────────────────────────

    def set_integration_time(self, seconds: float) -> None:
        self._integration_time_s = seconds
        if not self._offline:
            self._dll.tlccs_setIntegrationTime(self._handle, seconds)

    def get_integration_time(self) -> float:
        if self._offline:
            return self._integration_time_s
        t = C.c_double()
        self._dll.tlccs_getIntegrationTime(self._handle, C.byref(t))
        return t.value

    def measure(self) -> UVVisSpectrum:
        """Trigger a scan and return the spectrum."""
        if self._offline:
            return _synthetic_spectrum(self._integration_time_s)

        self._wait_for_idle()
        self._dll.tlccs_startScan(self._handle)

        integration_time = self.get_integration_time()
        self._wait_for_scan_ready(integration_time)

        data = (NUM_PIXELS * C.c_double)()
        rc = self._dll.tlccs_getScanData(self._handle, data)
        if rc != 0:
            raise UVVisCCSMeasurementError(
                f"tlccs_getScanData failed with code {rc}"
            )

        intensities = tuple(data)
        return UVVisSpectrum(
            wavelengths=self._wavelengths,
            intensities=intensities,
            integration_time_s=integration_time,
        )

    def get_device_info(self) -> list[str]:
        if self._offline:
            return ["Thorlabs", "CCS100", "OFFLINE", "1.0.0", "OfflineDriver"]
        buffers = [(256 * C.c_char)() for _ in range(5)]
        self._dll.tlccs_identificationQuery(self._handle, *buffers)
        return [buf.value.decode() for buf in buffers]

    # ── Private helpers ───────────────────────────────────────────────────

    def _configure_dll_prototypes(self) -> None:
        dll = self._dll
        dll.tlccs_init.argtypes = [
            C.c_char_p, C.c_bool, C.c_bool, C.POINTER(C.c_uint32),
        ]
        dll.tlccs_init.restype = C.c_int
        dll.tlccs_identificationQuery.argtypes = [
            C.c_uint32, C.c_char_p, C.c_char_p,
            C.c_char_p, C.c_char_p, C.c_char_p,
        ]
        dll.tlccs_identificationQuery.restype = C.c_int
        dll.tlccs_getWavelengthData.argtypes = [
            C.c_uint32, C.c_int16,
            C.POINTER(C.c_double), C.POINTER(C.c_double), C.POINTER(C.c_double),
        ]
        dll.tlccs_getWavelengthData.restype = C.c_int
        dll.tlccs_getDeviceStatus.argtypes = [
            C.c_uint32, C.POINTER(C.c_int32),
        ]
        dll.tlccs_getDeviceStatus.restype = C.c_int
        dll.tlccs_setIntegrationTime.argtypes = [C.c_uint32, C.c_double]
        dll.tlccs_setIntegrationTime.restype = C.c_int
        dll.tlccs_getIntegrationTime.argtypes = [
            C.c_uint32, C.POINTER(C.c_double),
        ]
        dll.tlccs_getIntegrationTime.restype = C.c_int
        dll.tlccs_startScan.argtypes = [C.c_uint32]
        dll.tlccs_startScan.restype = C.c_int
        dll.tlccs_getScanData.argtypes = [C.c_uint32, C.POINTER(C.c_double)]
        dll.tlccs_getScanData.restype = C.c_int
        dll.tlccs_close.argtypes = [C.c_uint32]
        dll.tlccs_close.restype = C.c_int

    def _load_wavelength_data(self) -> None:
        data = (NUM_PIXELS * C.c_double)()
        wmin = C.c_double()
        wmax = C.c_double()
        rc = self._dll.tlccs_getWavelengthData(
            self._handle, 0, data, C.byref(wmin), C.byref(wmax),
        )
        if rc != 0:
            raise UVVisCCSConnectionError(
                f"tlccs_getWavelengthData failed with code {rc}"
            )
        self._wavelengths = tuple(data)

    def _get_status(self) -> tuple[bool, bool]:
        status = C.c_int32()
        self._dll.tlccs_getDeviceStatus(self._handle, C.byref(status))
        idle = bool(status.value & _STATUS_IDLE)
        scan_ready = bool(status.value & _STATUS_SCAN_READY)
        return idle, scan_ready

    def _wait_for_idle(self) -> None:
        deadline = time.monotonic() + _IDLE_TIMEOUT_S
        while time.monotonic() < deadline:
            idle, _ = self._get_status()
            if idle:
                return
            time.sleep(_POLL_INTERVAL_S)
        raise UVVisCCSTimeoutError(
            f"Spectrometer not idle after {_IDLE_TIMEOUT_S}s"
        )

    def _wait_for_scan_ready(self, integration_time: float) -> None:
        poll = max(integration_time / 10, _POLL_INTERVAL_S)
        deadline = time.monotonic() + _IDLE_TIMEOUT_S
        while time.monotonic() < deadline:
            _, scan_ready = self._get_status()
            if scan_ready:
                return
            time.sleep(poll)
        raise UVVisCCSTimeoutError(
            f"Scan not ready after {_IDLE_TIMEOUT_S}s"
        )
