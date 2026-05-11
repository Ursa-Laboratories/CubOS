"""Deck: runtime container for loaded labware with target resolution."""

from __future__ import annotations

from typing import Dict, Iterator

from .labware.labware import Coordinate3D, Labware


class Deck:
    """
    Runtime container holding labware loaded from a deck YAML.

    Provides dict-like access to labware by key, and a
    ``resolve_coordinate()`` method that translates target strings (e.g.
    'plate_1.A1') into absolute deck coordinates.
    """

    def __init__(self, labware: Dict[str, Labware]) -> None:
        self._labware = dict(labware)

    @property
    def labware(self) -> Dict[str, Labware]:
        return self._labware

    def resolve_coordinate(self, target: str) -> Coordinate3D:
        """
        Resolve a target string to an absolute deck coordinate.

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
                raise KeyError(f"No nested labware '{target}' on deck.") from exc
        return labware

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
