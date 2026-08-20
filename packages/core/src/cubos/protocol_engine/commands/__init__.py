"""Protocol commands package.

Importing this package triggers all @protocol_command decorators,
populating the CommandRegistry.
"""

from . import camera, capper, home, lights, measure, move, pause, pipette, scan  # noqa: F401 -- side-effect imports for registration

__all__ = [
    "camera",
    "capper",
    "home",
    "lights",
    "measure",
    "move",
    "pause",
    "pipette",
    "scan",
]
