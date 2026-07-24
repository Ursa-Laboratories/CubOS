from cubos.instruments.base_instrument import InstrumentError


class ASMIError(InstrumentError):
    """Base exception for all ASMI instrument errors."""


class ASMIConnectionError(ASMIError):
    """Raised when the GoDirect force sensor cannot be found or opened."""


class ASMICommandError(ASMIError):
    """Raised when a sensor command fails (e.g. read error)."""


class ASMITimeoutError(ASMIError):
    """Raised when the sensor does not respond within the timeout period."""
