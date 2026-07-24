from cubos.instruments.base_instrument import InstrumentError


class UVVisCCSError(InstrumentError):
    """Base exception for Thorlabs CCS spectrometer errors."""


class UVVisCCSConnectionError(UVVisCCSError):
    """Raised when the spectrometer cannot be found or the DLL fails to load."""


class UVVisCCSMeasurementError(UVVisCCSError):
    """Raised when a scan fails or returns invalid data."""


class UVVisCCSTimeoutError(UVVisCCSError):
    """Raised when the spectrometer does not reach idle or scan-ready in time."""
