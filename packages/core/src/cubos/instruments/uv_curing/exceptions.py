from cubos.instruments.base_instrument import InstrumentError


class UVCuringError(InstrumentError):
    """Base exception for all UV curing instrument errors."""


class UVCuringConnectionError(UVCuringError):
    """Raised when the OmniCure cannot be found or opened."""


class UVCuringCommandError(UVCuringError):
    """Raised when a serial command fails or gets an error response."""


class UVCuringTimeoutError(UVCuringError):
    """Raised when the OmniCure does not respond within the timeout."""
