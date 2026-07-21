from cubos.instruments.base_instrument import InstrumentError


class FilmetricsError(InstrumentError):
    """Base exception for Filmetrics instrument errors."""


class FilmetricsConnectionError(FilmetricsError):
    """Raised when the Filmetrics exe cannot be launched or the process dies."""


class FilmetricsCommandError(FilmetricsError):
    """Raised on command timeout or command failure."""


class FilmetricsParseError(FilmetricsError):
    """Raised when output from the Filmetrics process has an unexpected format."""
