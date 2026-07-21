"""Protocol engine exception types."""


class ProtocolLoaderError(Exception):
    """Human-friendly protocol loader error intended for CLI output."""


class ProtocolExecutionError(Exception):
    """Error raised during protocol step execution."""


class GantryHealthCheckError(Exception):
    """Raised when the gantry fails its health check before a protocol run."""
