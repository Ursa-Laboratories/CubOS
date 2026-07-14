"""Coordinate normalization helpers for the gantry boundary.

CubOS speaks the deck-origin frame at the high-level gantry boundary:
front-left-bottom origin, +X operator-right, +Y back, +Z up. Controller
configuration is responsible for making raw GRBL/WPos reports match that
frame, so outgoing values are normalized without applying hidden sign flips.
"""

from __future__ import annotations

import re
from typing import overload

from .coordinates import Coordinates

_STATUS_COORD_PATTERN = re.compile(
    r"(?P<label>[WM]Pos:)"
    r"(?P<x>[+-]?(?:\d+(?:\.\d*)?|\.\d+)),"
    r"(?P<y>[+-]?(?:\d+(?:\.\d*)?|\.\d+)),"
    r"(?P<z>[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
)


def _normalize(value: float) -> float:
    normalized = float(value)
    if abs(normalized) < 1e-12:
        return 0.0
    return normalized


def _format_like(original_token: str, value: float) -> str:
    if "." in original_token:
        decimals = len(original_token.split(".", maxsplit=1)[1])
        return f"{value:.{decimals}f}"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


@overload
def to_machine_coordinates(x: float, y: float, z: float) -> tuple[float, float, float]:
    ...


@overload
def to_machine_coordinates(coords: Coordinates) -> Coordinates:
    ...


def to_machine_coordinates(
    x_or_coords: float | Coordinates,
    y: float | None = None,
    z: float | None = None,
) -> tuple[float, float, float] | Coordinates:
    """Normalize CubOS deck-frame coordinates before sending to the gantry."""
    if isinstance(x_or_coords, Coordinates):
        return Coordinates(
            _normalize(x_or_coords.x),
            _normalize(x_or_coords.y),
            _normalize(x_or_coords.z),
        )
    if y is None or z is None:
        raise TypeError("Expected x, y, z floats when not passing a Coordinates object.")
    return (_normalize(x_or_coords), _normalize(y), _normalize(z))


def translate_status_string(status: str) -> str:
    """Normalize WPos/MPos fields in a GRBL status line."""

    def _replace(match: re.Match[str]) -> str:
        tx = _format_like(match.group("x"), _normalize(float(match.group("x"))))
        ty = _format_like(match.group("y"), _normalize(float(match.group("y"))))
        tz = _format_like(match.group("z"), _normalize(float(match.group("z"))))
        return f"{match.group('label')}{tx},{ty},{tz}"

    return _STATUS_COORD_PATTERN.sub(_replace, status)
