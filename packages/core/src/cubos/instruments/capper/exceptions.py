from cubos.instruments.base_instrument import InstrumentError


class CapperError(InstrumentError):
    """Base exception for all capper/decapper instrument errors."""


class CapperConnectionError(CapperError):
    """Raised when the connection to the capper hardware cannot be established."""


class CapperCommandError(CapperError):
    """Raised when a command fails or the hardware returns an error response."""


class CapperTimeoutError(CapperError):
    """Raised when the hardware does not respond within the timeout period."""


class CapperConfigError(CapperError):
    """Raised for invalid capper instrument configuration."""


class CapperSensorFault(CapperError):
    """Raised when the cap sensor does not confirm the expected state.

    Covers both a timeout waiting for a sensor reading and a reading that
    contradicts the expected post-actuation cap state (e.g. the sensor still
    reports a cap present after a release action). Callers must treat this as
    a fail-closed condition: no further liquid handling on the affected vial
    until an operator reconciles the durable cap state.
    """
