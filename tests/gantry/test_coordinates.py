"""Unit tests for the Coordinates value object."""

from __future__ import annotations

import pytest

from gantry.coordinates import Coordinates


def test_attributes_round_to_six_decimal_places():
    c = Coordinates(1.1234567, 2.0, -3.9999999)
    assert c.x == 1.123457
    assert c.y == 2.0
    assert c.z == -4.0


def test_setters_reject_non_numeric():
    c = Coordinates(0, 0, 0)
    for axis in ("x", "y", "z"):
        with pytest.raises(ValueError):
            setattr(c, axis, "1.0")


def test_setters_mutate_in_place():
    c = Coordinates(0, 0, 0)
    c.x = 5.0
    c.y = -2.5
    c.z = 1.0
    assert (c.x, c.y, c.z) == (5.0, -2.5, 1.0)


def test_iter_yields_xyz_in_order():
    c = Coordinates(1, 2, 3)
    assert list(c) == [1.0, 2.0, 3.0]


def test_equality_compares_components():
    assert Coordinates(1, 2, 3) == Coordinates(1.0, 2.0, 3.0)
    assert Coordinates(1, 2, 3) != Coordinates(1, 2, 4)
    assert Coordinates(1, 2, 3) != (1, 2, 3)


def test_index_and_key_access_match_attributes():
    c = Coordinates(10, 20, 30)
    assert c[0] == c["x"] == c.x
    assert c[1] == c["y"] == c.y
    assert c[2] == c["z"] == c.z


def test_index_and_key_assignment_match_attributes():
    c = Coordinates(0, 0, 0)
    c[0] = 1
    c["y"] = 2
    c[2] = 3
    assert (c.x, c.y, c.z) == (1.0, 2.0, 3.0)


def test_invalid_index_raises():
    c = Coordinates(0, 0, 0)
    with pytest.raises(IndexError):
        _ = c[3]
    with pytest.raises(IndexError):
        c["w"] = 1


def test_to_dict_returns_xyz_floats():
    c = Coordinates(1, 2, 3)
    assert c.to_dict() == {"x": 1.0, "y": 2.0, "z": 3.0}


def test_repr_round_trips_visually():
    c = Coordinates(1.0, 2.0, 3.0)
    assert repr(c) == "Coordinates(x=1.0, y=2.0, z=3.0)"


def test_str_format():
    assert str(Coordinates(1, 2, 3)) == "(1.0, 2.0, 3.0)"
