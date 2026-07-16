"""Deterministic stock/waste container selection for compound liquid commands.

Selection reads only generic, machine-agnostic labware metadata --
``Vial.role``/``Vial.solution``/``Vial.allowed_solutions`` (see
``cubos.deck.labware.container_role``) -- plus a caller-supplied
current-volume lookup. No machine-name branches and no vial IDs are ever
embedded in protocol code; a protocol names a ``solution`` and a role, and
the concrete container is resolved here.

The same pure algorithm runs in two places:

* At protocol runtime (``cubos.protocol_engine.commands.pipette``), backed
  by ``DataStore.get_fluid_container`` for the current tracked volume.
* Offline (``cubos.validation.fluid_volumes``), backed by a simulated
  volume table seeded from a loaded ``initial-fluids`` YAML, so automatic
  selection is statically checkable whenever an initial-fluids file is
  supplied to ``validate_setup``/``run_setup_validation``.

Selection order (documented, stable, and depended on by tests): candidates
are visited in ``sorted(deck.volume_labware)`` key order (ascending
labware-key string sort); a matching ``VialGrid`` visits its own vials in
canonical position order (``VialGrid.vials`` dict order -- the row-major
order the deck loader derives them in, e.g. A1, A2, ..., B1, ...). The
first candidate that satisfies the volume constraint is selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from cubos.deck.deck import Deck, DeckLabwareTarget
from cubos.deck.labware.container_role import STOCK, WASTE
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.vial_grid import VialGrid

_VOLUME_TOLERANCE_UL = 1e-6

# Returns the current tracked volume (uL) of a candidate container, or
# ``None`` when it is unknown (offline validation without an initial-fluids
# seed for that container) -- an unknown-volume candidate is never selected.
CurrentVolumeLookup = Callable[[DeckLabwareTarget], "Optional[float]"]


class LiquidSelectionError(ValueError):
    """Raised when automatic stock/waste selection has no valid candidate."""


@dataclass(frozen=True)
class RejectedCandidate:
    """One considered-but-rejected candidate, for diagnostic error messages."""

    position: str
    reason: str


def target_position(target: DeckLabwareTarget) -> str:
    """Return the deck-target string form of a resolved target."""
    if target.location_id:
        return f"{target.labware_key}.{target.location_id}"
    return target.labware_key


def iter_role_candidates(
    deck: Deck, role: str,
) -> Iterator[tuple[DeckLabwareTarget, Vial]]:
    """Yield ``(target, vial)`` pairs for every container matching *role*.

    Stable order: see module docstring.
    """
    for labware_key in sorted(deck.volume_labware):
        labware = deck.volume_labware[labware_key]
        if isinstance(labware, Vial):
            if labware.role == role:
                yield DeckLabwareTarget(labware_key, labware, None), labware
        elif isinstance(labware, VialGrid):
            for location_id, vial in labware.vials.items():
                if vial.role == role:
                    yield (
                        DeckLabwareTarget(labware_key, labware, location_id),
                        vial,
                    )


def select_stock_container(
    deck: Deck,
    solution: str,
    requested_volume_ul: float,
    current_volume: CurrentVolumeLookup,
) -> DeckLabwareTarget:
    """Select a ``role=stock`` container whose ``solution`` matches.

    A candidate is eligible when
    ``tracked_volume - dead_volume_reserve >= requested_volume_ul``
    (``dead_volume_reserve`` is the candidate vial's own ``dead_volume_ul``).
    Raises :class:`LiquidSelectionError` when no eligible candidate exists,
    with a diagnostic listing every same-solution candidate considered and
    why it was rejected.
    """
    if not isinstance(solution, str) or not solution.strip():
        raise LiquidSelectionError("solution must be a non-empty string.")
    if (
        isinstance(requested_volume_ul, bool)
        or not isinstance(requested_volume_ul, (int, float))
        or requested_volume_ul <= 0
    ):
        raise LiquidSelectionError(
            f"requested_volume_ul must be a positive number, got "
            f"{requested_volume_ul!r}."
        )

    rejected: list[RejectedCandidate] = []
    for target, vial in iter_role_candidates(deck, STOCK):
        if vial.solution != solution:
            continue
        position = target_position(target)
        volume = current_volume(target)
        if volume is None:
            rejected.append(RejectedCandidate(position, "current volume unknown"))
            continue
        dead_volume_ul = float(vial.dead_volume_ul or 0.0)
        available = volume - dead_volume_ul
        if available + _VOLUME_TOLERANCE_UL >= requested_volume_ul:
            return target
        rejected.append(RejectedCandidate(
            position,
            f"only {available:g} uL available above its {dead_volume_ul:g} uL "
            f"dead-volume reserve (current volume {volume:g} uL, need "
            f"{requested_volume_ul:g} uL)",
        ))

    if not rejected:
        raise LiquidSelectionError(
            f"No role={STOCK!r} container with solution={solution!r} is "
            "defined on the deck."
        )
    detail = "; ".join(f"{c.position}: {c.reason}" for c in rejected)
    raise LiquidSelectionError(
        f"No role={STOCK!r} container with solution={solution!r} has "
        f"{requested_volume_ul:g} uL available: {detail}."
    )


def select_waste_container(
    deck: Deck,
    requested_volume_ul: float,
    current_volume: CurrentVolumeLookup,
    *,
    solution: Optional[str] = None,
) -> DeckLabwareTarget:
    """Select a ``role=waste`` container with headroom for the request.

    Compatibility policy: a candidate whose ``allowed_solutions`` is
    ``None`` accepts anything (the default). A candidate with an explicit
    ``allowed_solutions`` list is only eligible when *solution* is known
    (non-``None``) and is a member of that list.

    Headroom policy mirrors Feature 04's destination-overflow guard
    (``_liquid_transfer.validate_destination_overflow``): the hard ceiling
    is the candidate's ``working_volume_ul``, not its raw ``capacity_ul``.
    """
    if (
        isinstance(requested_volume_ul, bool)
        or not isinstance(requested_volume_ul, (int, float))
        or requested_volume_ul <= 0
    ):
        raise LiquidSelectionError(
            f"requested_volume_ul must be a positive number, got "
            f"{requested_volume_ul!r}."
        )

    rejected: list[RejectedCandidate] = []
    considered = 0
    for target, vial in iter_role_candidates(deck, WASTE):
        if vial.allowed_solutions is not None and (
            solution is None or solution not in vial.allowed_solutions
        ):
            continue
        considered += 1
        position = target_position(target)
        volume = current_volume(target)
        if volume is None:
            rejected.append(RejectedCandidate(position, "current volume unknown"))
            continue
        working_volume_ul = float(vial.working_volume_ul)
        projected = volume + requested_volume_ul
        if projected <= working_volume_ul + _VOLUME_TOLERANCE_UL:
            return target
        rejected.append(RejectedCandidate(
            position,
            f"projected {projected:g} uL exceeds its {working_volume_ul:g} uL "
            f"working volume (current volume {volume:g} uL)",
        ))

    if considered == 0:
        compat = f" accepting solution={solution!r}" if solution else ""
        raise LiquidSelectionError(
            f"No role={WASTE!r} container{compat} is defined on the deck."
        )
    detail = "; ".join(f"{c.position}: {c.reason}" for c in rejected)
    raise LiquidSelectionError(
        f"No role={WASTE!r} container has headroom for "
        f"{requested_volume_ul:g} uL: {detail}."
    )


__all__ = [
    "CurrentVolumeLookup",
    "LiquidSelectionError",
    "RejectedCandidate",
    "iter_role_candidates",
    "select_stock_container",
    "select_waste_container",
    "target_position",
]
