"""Unit tests for the pure stock/waste selection algorithm.

``cubos.protocol_engine.commands._liquid_selection`` is deliberately
decoupled from ``DataStore``/YAML loading: it only needs a ``Deck`` (for
role/solution metadata) and a plain ``current_volume`` callback. These
tests build minimal decks directly and drive the callback explicitly so the
selection order/rejection logic is pinned down independent of any runtime
or offline-validation caller.
"""

from __future__ import annotations

import pytest

from cubos.deck.deck import Deck, DeckLabwareTarget
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.deck.labware.vial_grid import VialGrid
from cubos.protocol_engine.commands._liquid_selection import (
    LiquidSelectionError,
    iter_role_candidates,
    select_stock_container,
    select_waste_container,
    target_position,
)


def _vial(name, *, role=None, solution=None, allowed_solutions=None,
          capacity_ul=1000.0, working_volume_ul=1000.0, dead_volume_ul=0.0,
          x=0.0, y=0.0, z=0.0) -> Vial:
    return Vial(
        name=name,
        role=role,
        solution=solution,
        allowed_solutions=allowed_solutions,
        height=57.0,
        diameter=28.0,
        location=Coordinate3D(x=x, y=y, z=z),
        capacity_ul=capacity_ul,
        working_volume_ul=working_volume_ul,
        dead_volume_ul=dead_volume_ul,
    )


def _deck(labware: dict) -> Deck:
    return Deck(labware=dict(labware), volume_labware=dict(labware))


def _volumes(mapping: dict) -> callable:
    """Return a lookup keyed by target_position(target)."""
    def _lookup(target):
        return mapping.get(target_position(target))
    return _lookup


# ─── select_stock_container ────────────────────────────────────────────────


class TestSelectStockContainer:

    def test_no_matching_role_or_solution_raises(self):
        deck = _deck({"s1": _vial("s1", role="stock", solution="ethanol")})
        with pytest.raises(LiquidSelectionError, match="No role='stock'"):
            select_stock_container(deck, "water", 10.0, _volumes({"s1": 1000.0}))

    def test_insufficient_volume_after_dead_volume_reserve_raises(self):
        deck = _deck({
            "s1": _vial("s1", role="stock", solution="water", dead_volume_ul=100.0),
        })
        # 150 current - 100 dead volume = 50 available; ask for 60.
        with pytest.raises(LiquidSelectionError, match="dead-volume"):
            select_stock_container(deck, "water", 60.0, _volumes({"s1": 150.0}))

    def test_dead_volume_reserve_exactly_at_boundary_succeeds(self):
        deck = _deck({
            "s1": _vial("s1", role="stock", solution="water", dead_volume_ul=100.0),
        })
        target = select_stock_container(deck, "water", 50.0, _volumes({"s1": 150.0}))
        assert target_position(target) == "s1"

    def test_unknown_current_volume_is_rejected_not_selected(self):
        deck = _deck({"s1": _vial("s1", role="stock", solution="water")})
        with pytest.raises(LiquidSelectionError, match="unknown"):
            select_stock_container(deck, "water", 10.0, _volumes({}))

    def test_multiple_candidates_pick_stable_labware_key_order(self):
        deck = _deck({
            "s2": _vial("s2", role="stock", solution="water"),
            "s1": _vial("s1", role="stock", solution="water"),
        })
        # Both eligible; "s1" sorts before "s2".
        target = select_stock_container(
            deck, "water", 10.0, _volumes({"s1": 1000.0, "s2": 1000.0}),
        )
        assert target_position(target) == "s1"

    def test_first_eligible_wins_when_earlier_candidate_lacks_volume(self):
        deck = _deck({
            "s1": _vial("s1", role="stock", solution="water"),
            "s2": _vial("s2", role="stock", solution="water"),
        })
        # s1 sorts first but has too little volume; s2 must be picked.
        target = select_stock_container(
            deck, "water", 500.0, _volumes({"s1": 10.0, "s2": 1000.0}),
        )
        assert target_position(target) == "s2"

    def test_non_stock_role_never_a_candidate(self):
        deck = _deck({"w1": _vial("w1", role="waste", solution="water")})
        with pytest.raises(LiquidSelectionError):
            select_stock_container(deck, "water", 10.0, _volumes({"w1": 1000.0}))

    def test_vial_with_no_role_never_a_candidate(self):
        deck = _deck({"v1": _vial("v1", role=None, solution="water")})
        with pytest.raises(LiquidSelectionError):
            select_stock_container(deck, "water", 10.0, _volumes({"v1": 1000.0}))

    def test_alias_resolution_selects_the_canonical_vial_grid_position(self):
        grid = VialGrid(
            name="reagents",
            rows=1,
            columns=2,
            vials={
                "A1": _vial("A1", role="stock", solution="water"),
                "A2": _vial("A2", role="stock", solution="buffer"),
            },
            aliases={"buffer_alias": "A2"},
        )
        deck = _deck({"reagents": grid})
        target = select_stock_container(
            deck, "buffer", 10.0, _volumes({"reagents.A1": 0.0, "reagents.A2": 500.0}),
        )
        assert target_position(target) == "reagents.A2"
        # The alias itself is not part of selection (selection walks
        # canonical positions), but resolves to the same underlying vial --
        # confirm canonicalization agrees with what selection returned.
        assert deck.canonicalize_target("reagents.buffer_alias") == "reagents.A2"

    def test_blank_solution_rejected(self):
        deck = _deck({"s1": _vial("s1", role="stock", solution="water")})
        with pytest.raises(LiquidSelectionError, match="non-empty"):
            select_stock_container(deck, "", 10.0, _volumes({"s1": 1000.0}))

    def test_non_positive_volume_rejected(self):
        deck = _deck({"s1": _vial("s1", role="stock", solution="water")})
        with pytest.raises(LiquidSelectionError, match="positive"):
            select_stock_container(deck, "water", 0.0, _volumes({"s1": 1000.0}))


# ─── select_waste_container ────────────────────────────────────────────────


class TestSelectWasteContainer:

    def test_no_waste_role_on_deck_raises(self):
        deck = _deck({"s1": _vial("s1", role="stock", solution="water")})
        with pytest.raises(LiquidSelectionError, match="No role='waste'"):
            select_waste_container(deck, 10.0, _volumes({"s1": 0.0}))

    def test_no_headroom_raises(self):
        deck = _deck({
            "w1": _vial("w1", role="waste", working_volume_ul=100.0),
        })
        # 90 + 20 = 110 > 100 working volume.
        with pytest.raises(LiquidSelectionError, match="headroom"):
            select_waste_container(deck, 20.0, _volumes({"w1": 90.0}))

    def test_headroom_uses_working_volume_not_capacity(self):
        deck = _deck({
            "w1": _vial(
                "w1", role="waste", capacity_ul=200.0, working_volume_ul=100.0,
            ),
        })
        # 90 + 20 = 110 fits under capacity (200) but not working volume (100).
        with pytest.raises(LiquidSelectionError, match="headroom"):
            select_waste_container(deck, 20.0, _volumes({"w1": 90.0}))

    def test_exact_headroom_boundary_succeeds(self):
        deck = _deck({
            "w1": _vial("w1", role="waste", working_volume_ul=100.0),
        })
        target = select_waste_container(deck, 20.0, _volumes({"w1": 80.0}))
        assert target_position(target) == "w1"

    def test_default_accept_all_when_allowed_solutions_unset(self):
        deck = _deck({"w1": _vial("w1", role="waste")})
        target = select_waste_container(
            deck, 10.0, _volumes({"w1": 0.0}), solution="anything",
        )
        assert target_position(target) == "w1"
        # Also accepts an unknown (None) solution.
        target = select_waste_container(deck, 10.0, _volumes({"w1": 0.0}))
        assert target_position(target) == "w1"

    def test_allowed_solutions_restricts_to_listed_solutions(self):
        deck = _deck({
            "w1": _vial("w1", role="waste", allowed_solutions=["water"]),
        })
        target = select_waste_container(
            deck, 10.0, _volumes({"w1": 0.0}), solution="water",
        )
        assert target_position(target) == "w1"

    def test_allowed_solutions_rejects_incompatible_solution(self):
        deck = _deck({
            "w1": _vial("w1", role="waste", allowed_solutions=["ethanol"]),
        })
        with pytest.raises(LiquidSelectionError, match="No role='waste'"):
            select_waste_container(
                deck, 10.0, _volumes({"w1": 0.0}), solution="water",
            )

    def test_allowed_solutions_rejects_unknown_solution(self):
        deck = _deck({
            "w1": _vial("w1", role="waste", allowed_solutions=["water"]),
        })
        # solution=None is "unknown" -- a restricted-list candidate is never
        # picked blind.
        with pytest.raises(LiquidSelectionError):
            select_waste_container(deck, 10.0, _volumes({"w1": 0.0}))

    def test_multiple_candidates_pick_stable_labware_key_order(self):
        deck = _deck({
            "w2": _vial("w2", role="waste", working_volume_ul=1000.0),
            "w1": _vial("w1", role="waste", working_volume_ul=1000.0),
        })
        target = select_waste_container(deck, 10.0, _volumes({"w1": 0.0, "w2": 0.0}))
        assert target_position(target) == "w1"

    def test_unknown_current_volume_is_rejected_not_selected(self):
        deck = _deck({"w1": _vial("w1", role="waste")})
        with pytest.raises(LiquidSelectionError, match="unknown"):
            select_waste_container(deck, 10.0, _volumes({}))


# ─── iter_role_candidates ordering ─────────────────────────────────────────


def test_iter_role_candidates_visits_vial_grid_in_canonical_position_order():
    grid = VialGrid(
        name="grid",
        rows=1,
        columns=3,
        vials={
            "A1": _vial("A1", role="waste"),
            "A2": _vial("A2", role="waste"),
            "A3": _vial("A3", role="waste"),
        },
    )
    deck = _deck({"grid": grid})
    positions = [
        target_position(target)
        for target, _vial_obj in iter_role_candidates(deck, "waste")
    ]
    assert positions == ["grid.A1", "grid.A2", "grid.A3"]


def test_iter_role_candidates_sorts_top_level_labware_keys():
    deck = _deck({
        "zeta": _vial("zeta", role="stock", solution="x"),
        "alpha": _vial("alpha", role="stock", solution="x"),
        "mid": _vial("mid", role="stock", solution="x"),
    })
    positions = [
        target_position(target)
        for target, _vial_obj in iter_role_candidates(deck, "stock")
    ]
    assert positions == ["alpha", "mid", "zeta"]
