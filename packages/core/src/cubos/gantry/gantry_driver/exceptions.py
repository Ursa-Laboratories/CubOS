"""Exceptions for the mill"""


class StatusReturnError(Exception):
    """Raised when the mill returns an error in the status"""

class MillConnectionError(Exception):
    """Raised when there is an error connecting to the mill"""


class CommandExecutionError(Exception):
    """Raised when there is an error executing a command"""


class LocationNotFound(Exception):
    """Raised when the mill cannot find its location"""


class CNCMillException(Exception):
    """Base exception for CNC mill errors."""
