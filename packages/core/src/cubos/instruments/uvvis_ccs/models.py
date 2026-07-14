from dataclasses import dataclass
from typing import Optional


NUM_PIXELS = 3648


@dataclass(frozen=True)
class UVVisSpectrum:
    """Immutable result of a single UV-Vis CCS spectrometer scan.

    Attributes:
        wavelengths: Wavelength array in nm (typically 3648 elements).
        intensities: Raw intensity counts from the detector.
        integration_time_s: Integration time used for this scan, in seconds.
    """

    wavelengths: tuple[float, ...]
    intensities: tuple[float, ...]
    integration_time_s: float

    @property
    def is_valid(self) -> bool:
        return (
            len(self.wavelengths) > 0
            and len(self.wavelengths) == len(self.intensities)
            and self.integration_time_s > 0
        )

    @property
    def num_pixels(self) -> int:
        return len(self.wavelengths)
