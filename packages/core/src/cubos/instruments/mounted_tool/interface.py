"""Generic mount-only tool interface."""

from cubos.instruments.base_instrument import BaseInstrument


class MountedToolInstrument(BaseInstrument):
    """Base class for mounted tools that CubOS can position but not actuate."""

