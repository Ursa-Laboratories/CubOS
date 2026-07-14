"""Protocol commands package.

Importing this package triggers all @protocol_command decorators,
populating the CommandRegistry.
"""

from . import home, measure, move, pause, pipette, scan  # noqa: F401 -- side-effect imports for registration

__all__ = ["home", "measure", "move", "pause", "pipette", "scan"]
