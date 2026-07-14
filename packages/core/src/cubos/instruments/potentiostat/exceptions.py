from cubos.instruments.base_instrument import InstrumentError


class PotentiostatError(InstrumentError):
    """Base exception for all potentiostat instrument errors."""


class PotentiostatConnectionError(PotentiostatError):
    """Raised when the SquidStat device cannot be opened or the vendor SDK is missing."""


class PotentiostatCommandError(PotentiostatError):
    """Raised when an experiment command fails or runs without an active connection."""


class PotentiostatTimeoutError(PotentiostatError):
    """Raised when an experiment exceeds its command_timeout before completing."""


class PotentiostatConfigError(PotentiostatError):
    """Raised when invalid experiment parameters are supplied."""
