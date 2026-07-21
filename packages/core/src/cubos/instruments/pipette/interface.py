"""Generic pipette instrument interface."""

from abc import abstractmethod

from cubos.instruments.base_instrument import BaseInstrument
from cubos.instruments.pipette.liquid_class import (
    IDENTITY_CORRECTION,
    LiquidClassConfigError,
    LiquidClassCorrection,
)
from cubos.instruments.pipette.models import AspirateResult, MixResult, PipetteStatus


class PipetteInstrument(BaseInstrument):
    """Base class for pipette implementations."""

    @property
    def liquid_classes(self) -> dict[str, LiquidClassCorrection]:
        """Return this instrument's configured liquid-class corrections.

        Empty by default (no vendor wiring required to opt out). Vendors
        that support per-liquid correction store parsed corrections on
        ``self._liquid_classes``.
        """
        return getattr(self, "_liquid_classes", {})

    def correction_for(self, liquid_class: str | None) -> LiquidClassCorrection:
        """Return the correction for *liquid_class*, or identity when unset."""
        if liquid_class is None:
            return IDENTITY_CORRECTION
        try:
            return self.liquid_classes[liquid_class]
        except KeyError:
            raise LiquidClassConfigError(
                f"Unknown liquid class {liquid_class!r}. Configured: "
                f"{sorted(self.liquid_classes)}."
            ) from None

    @property
    @abstractmethod
    def attached_tip_extension(self) -> float:
        """Return the active disposable-tip extension below the bare nozzle."""

    @abstractmethod
    def set_attached_tip_extension(self, extension_mm: float) -> None:
        """Record the current disposable-tip extension in millimeters."""

    @abstractmethod
    def clear_attached_tip_extension(self) -> None:
        """Clear any active disposable-tip extension."""

    @abstractmethod
    def home(self) -> None:
        """Home the pipette plunger."""

    @abstractmethod
    def prime(self, speed: float = 50.0) -> None:
        """Move the plunger to the priming position."""

    @abstractmethod
    def aspirate(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        """Aspirate the requested volume in microliters."""

    @abstractmethod
    def dispense(self, volume_ul: float, speed: float = 50.0) -> AspirateResult:
        """Dispense the requested volume in microliters."""

    @abstractmethod
    def blowout(self, speed: float = 50.0) -> None:
        """Move the plunger to the blowout position."""

    @abstractmethod
    def mix(
        self,
        volume_ul: float,
        repetitions: int = 3,
        speed: float = 50.0,
    ) -> MixResult:
        """Aspirate and dispense repeatedly to mix a liquid."""

    @abstractmethod
    def pick_up_tip(self, speed: float = 50.0) -> None:
        """Pick up a disposable tip."""

    @abstractmethod
    def drop_tip(self, speed: float = 50.0) -> None:
        """Drop the attached disposable tip."""

    @abstractmethod
    def get_status(self) -> PipetteStatus:
        """Return the current pipette status."""
