"""Mount-only tool instrument support."""

from cubos.instruments.mounted_tool.interface import MountedToolInstrument
from cubos.instruments.mounted_tool.vendors.mount_only import MountOnlyTool

__all__ = ["MountedToolInstrument", "MountOnlyTool"]

