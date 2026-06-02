"""Tests for gantry coordinate normalization helpers."""

from __future__ import annotations

import math

from gantry.coordinate_translator import (
    to_machine_coordinates,
    translate_status_string,
)
from gantry.coordinates import Coordinates


def test_to_machine_coordinates_preserves_xyz_without_sign_flip() -> None:
    assert to_machine_coordinates(150.0, 100.0, 40.0) == (150.0, 100.0, 40.0)


def test_zero_values_stay_zero() -> None:
    mx, my, mz = to_machine_coordinates(0.0, 0.0, 0.0)
    assert (mx, my, mz) == (0.0, 0.0, 0.0)


def test_coordinates_object_translation_returns_coordinates() -> None:
    coords = Coordinates(x=1.5, y=2.5, z=-3.5)
    machine = to_machine_coordinates(coords)
    assert isinstance(machine, Coordinates)
    assert (machine.x, machine.y, machine.z) == (1.5, 2.5, -3.5)


def test_translate_status_string_wpos_coordinates() -> None:
    status = "<Idle|WPos:150.000,100.000,-40.000|FS:0,0>"
    translated = translate_status_string(status)
    assert translated == "<Idle|WPos:150.000,100.000,-40.000|FS:0,0>"


def test_translate_status_string_mpos_coordinates() -> None:
    status = "<Idle|MPos:300.5,200.25,-80.125|Bf:15,127|FS:0,0>"
    translated = translate_status_string(status)
    assert translated == "<Idle|MPos:300.5,200.25,-80.125|Bf:15,127|FS:0,0>"


def test_translate_status_string_without_coordinates_is_passthrough() -> None:
    status = "<Idle|FS:0,0|Pn:X>"
    assert translate_status_string(status) == status


def test_machine_translation_handles_extreme_float_values() -> None:
    tiny = 1e-9
    huge = 1e9
    mx, my, mz = to_machine_coordinates(huge, tiny, -math.pi)
    assert mx == 1e9
    assert my == 1e-9
    assert mz == -math.pi
