"""Checks for the mock panda-like deck YAML fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from cubos.deck import TipRack, VialHolder, WellPlateHolder
from cubos.deck.loader import load_deck_from_yaml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_mock_panda_deck_yaml_loads_with_expected_reference_points():
    deck = load_deck_from_yaml(FIXTURES / "configs/deck/mock_panda_deck.yaml")

    assert isinstance(deck["tip_rack_left"], TipRack)
    assert deck.resolve_coordinate("tip_rack_left.A1").x == pytest.approx(168.0)
    assert deck.resolve_coordinate("tip_rack_left.A1").y == pytest.approx(58.0)
    assert isinstance(deck["tip_rack_right"], TipRack)
    assert deck.resolve_coordinate("tip_rack_right.A1").x == pytest.approx(236.0)

    assert isinstance(deck["well_plate_holder"], WellPlateHolder)
    assert deck.resolve_coordinate("well_plate_holder.plate.A1") == pytest.approx(
        deck.resolve_coordinate("well_plate_holder.plate")
    )
    assert deck.resolve_coordinate("well_plate_holder.plate.A1").z == pytest.approx(26.0)
    assert deck.resolve_coordinate("well_plate_holder.plate.B1").y == pytest.approx(62.0)

    assert isinstance(deck["vial_holder"], VialHolder)
    assert deck.resolve_coordinate("vial_holder.vial_1").z == pytest.approx(68.0)
    assert deck.resolve_coordinate("vial_holder.vial_9").y == pytest.approx(266.0)
