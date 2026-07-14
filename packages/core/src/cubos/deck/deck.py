"""Deck: runtime container for loaded labware with target resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator

from .labware.labware import Coordinate3D, Labware


@dataclass(frozen=True)
class DeckLabwareTarget:
    """Resolved labware path plus optional location/well id."""

    labware_key: str
    labware: Labware
    location_id: str | None = None

    @property
    def labware_name(self) -> str:
        return getattr(self.labware, "name", self.labware_key)


class Deck:
    """
    Runtime container holding labware loaded from a deck YAML.

    Provides dict-like access to labware by key plus:

    - ``resolve_coordinate()``: resolve a deck-coordinate target string (e.g.
      ``"plate_1.A1"``) into a coordinate.
    - ``resolve_labware()``: resolve a nested labware object path (e.g.
      ``"plate_holder.plate"``).
    - ``resolve_labware_target()``: split an addressable deck target into
      the owning labware path plus optional location/well id.
    """

    def __init__(self, labware: Dict[str, Labware]) -> None:
        self._labware = dict(labware)

    @property
    def labware(self) -> Dict[str, Labware]:
        return self._labware

    def resolve_coordinate(self, target: str) -> Coordinate3D:
        """
        Resolve a deck coordinate target to an absolute ``Coordinate3D``.

        Formats:
            'plate_1.A1'  -> well A1 on plate_1
            'vial_1'      -> vial center (initial position)
            'plate_1'     -> plate initial position (A1)
        """
        if "." in target:
            labware_key, location_id = target.split(".", 1)
            return self._get_labware(labware_key).get_location(location_id)
        return self._get_labware(target).get_initial_position()

    def resolve_labware(self, target: str) -> Labware:
        """Resolve a top-level or nested labware path to a Labware object.

        Formats:
            'plate_1'            -> top-level plate_1 object
            'plate_holder.plate' -> contained plate object
        """
        parts = target.split(".")
        labware = self._get_labware(parts[0])

        for child_name in parts[1:]:
            children = getattr(labware, "contained_labware", {})
            try:
                labware = children[child_name]
            except KeyError as exc:
                raise KeyError(
                    f"No nested labware '{child_name}' on deck."
                ) from exc
        return labware

    def resolve_labware_target(self, target: str) -> DeckLabwareTarget:
        """Resolve the labware owner for a deck target.

        Formats:
            'vial_1'                 -> labware_key='vial_1', location_id=None
            'plate_1.A1'             -> labware_key='plate_1', location_id='A1'
            'plate_holder.plate.A1'  -> labware_key='plate_holder.plate',
                                       location_id='A1'
        """
        try:
            labware = self.resolve_labware(target)
        except KeyError:
            if "." not in target:
                raise
        else:
            return DeckLabwareTarget(
                labware_key=target,
                labware=labware,
                location_id=None,
            )

        labware_key, location_id = target.rsplit(".", 1)
        return DeckLabwareTarget(
            labware_key=labware_key,
            labware=self.resolve_labware(labware_key),
            location_id=location_id,
        )

    def _get_labware(self, key: str) -> Labware:
        try:
            return self._labware[key]
        except KeyError:
            raise KeyError(f"No labware '{key}' on deck.") from None

    def __getitem__(self, key: str) -> Labware:
        return self._get_labware(key)

    def __contains__(self, key: object) -> bool:
        return key in self._labware

    def __len__(self) -> int:
        return len(self._labware)

    def __iter__(self) -> Iterator[str]:
        return iter(self._labware)

    def __repr__(self) -> str:
        keys = ", ".join(self._labware.keys())
        return f"Deck([{keys}])"
