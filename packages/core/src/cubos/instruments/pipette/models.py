from dataclasses import dataclass
from enum import Enum


class PipetteFamily(Enum):
    OT2 = "OT2"
    FLEX = "FLEX"


@dataclass(frozen=True)
class PipetteConfig:
    """Static hardware description for a pipette model."""

    name: str
    family: PipetteFamily
    channels: int
    max_volume: float
    min_volume: float
    zero_position: float
    prime_position: float
    blowout_position: float
    drop_tip_position: float
    mm_to_ul: float


@dataclass(frozen=True)
class PipetteStatus:
    """Snapshot of pipette state returned by get_status()."""

    is_homed: bool
    position_mm: float
    max_volume: float
    has_tip: bool
    is_primed: bool

    @property
    def is_valid(self) -> bool:
        return self.max_volume > 0 and self.position_mm >= 0


@dataclass(frozen=True)
class AspirateResult:
    """Result of an aspirate or dispense operation."""

    success: bool
    volume_ul: float
    position_mm: float


@dataclass(frozen=True)
class MixResult:
    """Result of a mix (repeated aspirate/dispense) operation."""

    success: bool
    volume_ul: float
    repetitions: int


# ── Pipette model registry ───────────────────────────────────────────────────
# P300 uses real calibrated values from PANDA-BEAR.
# Other models have placeholder positions that need hardware calibration.

PIPETTE_MODELS: dict[str, PipetteConfig] = {
    # OT-2 single-channel
    "p20_single_gen2": PipetteConfig(
        name="p20_single_gen2",
        family=PipetteFamily.OT2,
        channels=1,
        max_volume=20.0,
        min_volume=1.0,
        zero_position=0.0,
        prime_position=5.0,       # placeholder
        blowout_position=7.0,     # placeholder
        drop_tip_position=10.0,   # placeholder
        mm_to_ul=0.025,           # placeholder
    ),
    "p300_single_gen2": PipetteConfig(
        name="p300_single_gen2",
        family=PipetteFamily.OT2,
        channels=1,
        max_volume=200.0,
        min_volume=20.0,
        zero_position=0.0,
        prime_position=36.0,      # calibrated from PANDA-BEAR
        blowout_position=46.0,    # calibrated from PANDA-BEAR
        drop_tip_position=60.0,   # calibrated from PANDA-BEAR
        mm_to_ul=0.1098,          # calibrated from PANDA-BEAR
    ),
    "p1000_single_gen2": PipetteConfig(
        name="p1000_single_gen2",
        family=PipetteFamily.OT2,
        channels=1,
        max_volume=1000.0,
        min_volume=100.0,
        zero_position=0.0,
        prime_position=40.0,      # placeholder
        blowout_position=50.0,    # placeholder
        drop_tip_position=65.0,   # placeholder
        mm_to_ul=0.55,            # placeholder
    ),
    # OT-2 multi-channel
    "p20_multi_gen2": PipetteConfig(
        name="p20_multi_gen2",
        family=PipetteFamily.OT2,
        channels=8,
        max_volume=20.0,
        min_volume=1.0,
        zero_position=0.0,
        prime_position=5.0,       # placeholder
        blowout_position=7.0,     # placeholder
        drop_tip_position=10.0,   # placeholder
        mm_to_ul=0.025,           # placeholder
    ),
    "p300_multi_gen2": PipetteConfig(
        name="p300_multi_gen2",
        family=PipetteFamily.OT2,
        channels=8,
        max_volume=200.0,
        min_volume=20.0,
        zero_position=0.0,
        prime_position=36.0,      # placeholder (same as single P300)
        blowout_position=46.0,    # placeholder
        drop_tip_position=60.0,   # placeholder
        mm_to_ul=0.1098,          # placeholder
    ),
    # Flex single-channel
    "flex_1channel_50": PipetteConfig(
        name="flex_1channel_50",
        family=PipetteFamily.FLEX,
        channels=1,
        max_volume=50.0,
        min_volume=1.0,
        zero_position=0.0,
        prime_position=8.0,       # placeholder
        blowout_position=11.0,    # placeholder
        drop_tip_position=15.0,   # placeholder
        mm_to_ul=0.04,            # placeholder
    ),
    "flex_1channel_1000": PipetteConfig(
        name="flex_1channel_1000",
        family=PipetteFamily.FLEX,
        channels=1,
        max_volume=1000.0,
        min_volume=5.0,
        zero_position=0.0,
        prime_position=40.0,      # placeholder
        blowout_position=50.0,    # placeholder
        drop_tip_position=65.0,   # placeholder
        mm_to_ul=0.55,            # placeholder
    ),
    # Flex multi-channel
    "flex_8channel_50": PipetteConfig(
        name="flex_8channel_50",
        family=PipetteFamily.FLEX,
        channels=8,
        max_volume=50.0,
        min_volume=1.0,
        zero_position=0.0,
        prime_position=8.0,       # placeholder
        blowout_position=11.0,    # placeholder
        drop_tip_position=15.0,   # placeholder
        mm_to_ul=0.04,            # placeholder
    ),
    "flex_8channel_1000": PipetteConfig(
        name="flex_8channel_1000",
        family=PipetteFamily.FLEX,
        channels=8,
        max_volume=1000.0,
        min_volume=5.0,
        zero_position=0.0,
        prime_position=40.0,      # placeholder
        blowout_position=50.0,    # placeholder
        drop_tip_position=65.0,   # placeholder
        mm_to_ul=0.55,            # placeholder
    ),
    "flex_96channel_1000": PipetteConfig(
        name="flex_96channel_1000",
        family=PipetteFamily.FLEX,
        channels=96,
        max_volume=1000.0,
        min_volume=5.0,
        zero_position=0.0,
        prime_position=40.0,      # placeholder
        blowout_position=50.0,    # placeholder
        drop_tip_position=65.0,   # placeholder
        mm_to_ul=0.55,            # placeholder
    ),
}
