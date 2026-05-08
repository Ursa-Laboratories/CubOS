"""Tests for the Deck class: labware container with target resolution."""

import pytest

from deck import Coordinate3D, WellPlate, Vial
from deck.deck import Deck


# ----- Fixtures -----

def _make_plate() -> WellPlate:
    return WellPlate(
        name="plate_1",
        model_name="test_96",
        length=127.71,
        width=85.43,
        height=14.10,
        rows=2,
        columns=2,
        wells={
            "A1": Coordinate3D(x=0.0, y=0.0, z=75.0),
            "A2": Coordinate3D(x=10.0, y=0.0, z=75.0),
            "B1": Coordinate3D(x=0.0, y=8.0, z=75.0),
            "B2": Coordinate3D(x=10.0, y=8.0, z=75.0),
        },
        capacity_ul=200.0,
        working_volume_ul=150.0,
    )


def _make_vial() -> Vial:
    return Vial(
        name="vial_1",
        model_name="standard_1_5ml",
        height=66.75,
        diameter=28.0,
        location=Coordinate3D(x=30.0, y=40.0, z=20.0),
        capacity_ul=1500.0,
        working_volume_ul=1200.0,
    )


def _make_deck() -> Deck:
    return Deck({"plate_1": _make_plate(), "vial_1": _make_vial()})


# ----- Construction -----

def test_deck_construction_stores_labware():
    """Deck wraps a dict of labware accessible via .labware."""
    deck = _make_deck()
    assert len(deck.labware) == 2
    assert isinstance(deck.labware["plate_1"], WellPlate)
    assert isinstance(deck.labware["vial_1"], Vial)


def test_deck_empty_labware_allowed():
    """Deck with no labware is valid."""
    deck = Deck({})
    assert len(deck.labware) == 0


# ----- Container protocol -----

def test_deck_getitem_returns_labware():
    """deck['key'] delegates to the labware dict."""
    deck = _make_deck()
    assert isinstance(deck["plate_1"], WellPlate)
    assert isinstance(deck["vial_1"], Vial)


def test_deck_getitem_missing_key_raises():
    """deck['unknown'] raises KeyError with clear message."""
    deck = _make_deck()
    with pytest.raises(KeyError, match="unknown"):
        deck["unknown"]


def test_deck_contains():
    """'key' in deck checks labware membership."""
    deck = _make_deck()
    assert "plate_1" in deck
    assert "vial_1" in deck
    assert "missing" not in deck


def test_deck_len():
    """len(deck) returns labware count."""
    deck = _make_deck()
    assert len(deck) == 2


def test_deck_iter():
    """Iterating over deck yields labware keys."""
    deck = _make_deck()
    assert set(deck) == {"plate_1", "vial_1"}


# ----- resolve() -----

def test_resolve_well_plate_with_location():
    """resolve('plate_1.A1') returns coordinate for well A1."""
    deck = _make_deck()
    coord = deck.resolve("plate_1.A1")
    assert coord == Coordinate3D(x=0.0, y=0.0, z=75.0)


def test_resolve_well_plate_another_well():
    """resolve('plate_1.B2') returns coordinate for well B2."""
    deck = _make_deck()
    coord = deck.resolve("plate_1.B2")
    assert coord == Coordinate3D(x=10.0, y=8.0, z=75.0)


def test_resolve_vial_bare_name():
    """resolve('vial_1') returns vial center (initial position)."""
    deck = _make_deck()
    coord = deck.resolve("vial_1")
    assert coord == Coordinate3D(x=30.0, y=40.0, z=20.0)


def test_resolve_plate_bare_name_returns_initial_position():
    """resolve('plate_1') with no location returns A1 (initial position)."""
    deck = _make_deck()
    coord = deck.resolve("plate_1")
    assert coord == Coordinate3D(x=0.0, y=0.0, z=75.0)


def test_resolve_unknown_labware_raises():
    """resolve('unknown.A1') raises KeyError for missing labware."""
    deck = _make_deck()
    with pytest.raises(KeyError, match="unknown"):
        deck.resolve("unknown.A1")


def test_resolve_unknown_labware_bare_raises():
    """resolve('unknown') raises KeyError for missing labware."""
    deck = _make_deck()
    with pytest.raises(KeyError, match="unknown"):
        deck.resolve("unknown")


def test_resolve_invalid_well_id_raises():
    """resolve('plate_1.Z99') raises KeyError for invalid well."""
    deck = _make_deck()
    with pytest.raises(KeyError, match="Z99"):
        deck.resolve("plate_1.Z99")


def test_resolve_vial_with_dot_location_raises():
    """resolve('vial_1.X') raises KeyError since vial has no sub-locations."""
    deck = _make_deck()
    with pytest.raises(KeyError):
        deck.resolve("vial_1.X")
