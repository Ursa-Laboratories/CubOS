"""Focused tests for durable deck-associated vial cap state.

Mirrors the organization of ``tests/data/test_tip_state.py``: cap state
hangs off the same ``fluid_state_sessions`` row a campaign's fluid state
uses, sharing its two-phase begin/complete operation journal and
single-pending-operation-per-session safety posture with fluid/tip state.
"""

from __future__ import annotations

import sqlite3

import pytest

from cubos.data import (
    CapStateConflictError,
    CapStateDeckMismatchError,
    CapStateError,
    CapStateNotFoundError,
    CapStateReconciliationRequiredError,
    DataStore,
    FluidStateReconciliationRequiredError,
)
from cubos.deck.loader import load_deck_from_yaml_safe

DECK_YAML = """\
labware:
  stock:
    type: vial
    name: stock
    height: 40.0
    diameter: 15.0
    location: {x: 5.0, y: 5.0, z: 20.0}
    capacity_ul: 500.0
    working_volume_ul: 400.0
    capped: true

  waste:
    type: vial
    name: waste
    height: 40.0
    diameter: 15.0
    location: {x: 20.0, y: 5.0, z: 20.0}
    capacity_ul: 500.0
    working_volume_ul: 400.0
    capped: false

  untracked:
    type: vial
    name: untracked
    height: 40.0
    diameter: 15.0
    location: {x: 35.0, y: 5.0, z: 20.0}
    capacity_ul: 500.0
    working_volume_ul: 400.0

  grid:
    type: vial_grid
    name: grid
    rows: 1
    columns: 2
    calibration:
      a1: {x: 50.0, y: 5.0, z: 20.0}
      a2: {x: 60.0, y: 5.0, z: 20.0}
    x_offset: 10.0
    y_offset: 10.0
    capacity_ul: 500.0
    working_volume_ul: 400.0
    vial_capped: true
"""


def _write_deck(tmp_path, text: str = DECK_YAML):
    path = tmp_path / "deck.yaml"
    path.write_text(text, encoding="utf-8")
    return path, load_deck_from_yaml_safe(path)


def _create_state(store, deck_path, deck, label="cap demo"):
    return store.create_fluid_state(deck_path, deck, label=label)


def _create_linked_campaign(store, state_id, description="cap test"):
    return store.create_campaign(description, fluid_state_id=state_id)


def _container(snapshot, labware_key, location_id=""):
    return next(
        row for row in snapshot["containers"]
        if row["labware_key"] == labware_key and row["location_id"] == location_id
    )


# ── Schema / seeding round-trips ────────────────────────────────────────────


def test_schema_has_cap_tables_and_pending_index(tmp_path):
    db_path = tmp_path / "state.db"
    store = DataStore(db_path)
    store.close()

    connection = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"cap_containers", "cap_operations"} <= tables
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "cap_operations_one_pending_per_state" in indexes
    finally:
        connection.close()


def test_create_seeds_cap_containers_from_declared_capped_vials(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)

    snapshot = store.get_cap_snapshot(state_id)
    keys = {(row["labware_key"], row["location_id"]) for row in snapshot["containers"]}
    assert keys == {
        ("stock", ""), ("waste", ""), ("grid", "A1"), ("grid", "A2"),
    }
    assert _container(snapshot, "stock")["status"] == "capped"
    assert _container(snapshot, "waste")["status"] == "uncapped"
    assert _container(snapshot, "grid", "A1")["status"] == "capped"


def test_untracked_vial_has_no_cap_state(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)

    assert store.get_cap_state(state_id, "untracked", "") is None


def test_resume_verifies_cap_registry(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)

    resumed = store.resume_fluid_state(state_id, deck_path, deck)
    assert resumed == state_id


def test_resume_rejects_deck_that_dropped_a_capped_vial(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)

    # A deck missing the `capped` declaration on `stock` no longer registers
    # a cap-state container for it -- the fingerprint changes first, so this
    # is expected to raise a deck-mismatch class of error (fingerprint or
    # registry mismatch), not silently resume.
    other_path, other_deck = _write_deck(
        tmp_path,
        DECK_YAML.replace("    capped: true\n", "", 1),
    )
    with pytest.raises(Exception):
        store.resume_fluid_state(state_id, other_path, other_deck)


# ── begin/complete decap ─────────────────────────────────────────────────


def test_begin_decap_requires_capped_state(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    with pytest.raises(CapStateError, match="expected 'capped'"):
        store.begin_cap_operation(
            state_id, "op1", "decap", "waste", "", campaign_id=campaign_id,
        )


def test_decap_then_cap_round_trip(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    should_execute = store.begin_cap_operation(
        state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id,
    )
    assert should_execute is True
    store.complete_cap_operation("decap-1")
    assert store.get_cap_state(state_id, "stock", "") == "uncapped"

    should_execute = store.begin_cap_operation(
        state_id, "cap-1", "cap", "stock", "", campaign_id=campaign_id,
    )
    assert should_execute is True
    store.complete_cap_operation("cap-1")
    assert store.get_cap_state(state_id, "stock", "") == "capped"


def test_begin_cap_operation_idempotent_replay_skips_execution(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    store.complete_cap_operation("decap-1")

    should_execute = store.begin_cap_operation(
        state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id,
    )
    assert should_execute is False


def test_begin_cap_operation_requires_campaign_link(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)

    with pytest.raises(CapStateError, match="campaign_id"):
        store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "")


def test_begin_cap_operation_rejects_untracked_vial(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    with pytest.raises(CapStateError, match="no durable cap state"):
        store.begin_cap_operation(
            state_id, "decap-1", "decap", "untracked", "", campaign_id=campaign_id,
        )


def test_begin_cap_operation_rejects_bad_operation_type(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    with pytest.raises(CapStateError):
        store.begin_cap_operation(
            state_id, "op1", "bogus", "stock", "", campaign_id=campaign_id,
        )


# ── Concurrent / pending-operation locks ────────────────────────────────


def test_second_decap_blocked_while_first_pending(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    # decap-1 is still "started" (never completed) -- a second cap operation
    # on a different vial must be blocked by the same single-in-flight-
    # physical-action journal fluid/tip operations use.
    with pytest.raises(CapStateReconciliationRequiredError):
        store.begin_cap_operation(
            state_id, "cap-1", "cap", "waste", "", campaign_id=campaign_id,
        )


def test_pending_decap_blocks_fluid_transfer(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)

    with pytest.raises(FluidStateReconciliationRequiredError):
        store.begin_fluid_transfer(
            state_id, "transfer-1", "waste", "stock", 10.0, campaign_id=campaign_id,
        )


def test_pending_fluid_transfer_blocks_decap(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)
    store.seed_fluid(state_id, "waste", 100.0)

    store.begin_fluid_transfer(
        state_id, "transfer-1", "waste", "untracked", 10.0, campaign_id=campaign_id,
    )

    with pytest.raises(CapStateReconciliationRequiredError):
        store.begin_cap_operation(
            state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id,
        )


# ── Reconciliation ────────────────────────────────────────────────────────


def test_mark_reconciliation_required_sets_container_status(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    store.mark_cap_reconciliation_required("decap-1", "serial timeout mid-capture")

    assert store.get_cap_state(state_id, "stock", "") == "reconciliation_required"


def test_new_operation_blocked_while_reconciliation_required(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    store.mark_cap_reconciliation_required("decap-1", "contradictory sensor")

    with pytest.raises(CapStateReconciliationRequiredError):
        store.begin_cap_operation(
            state_id, "decap-2", "decap", "stock", "", campaign_id=campaign_id,
        )


def test_resolve_applied(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    store.mark_cap_reconciliation_required("decap-1", "uncertain")
    store.resolve_cap_operation("decap-1", "applied", detail="operator confirmed uncapped")

    assert store.get_cap_state(state_id, "stock", "") == "uncapped"


def test_resolve_cancelled_reverts_to_previous_status(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    store.mark_cap_reconciliation_required("decap-1", "uncertain")
    store.resolve_cap_operation("decap-1", "not_applied", detail="operator saw cap still on")

    assert store.get_cap_state(state_id, "stock", "") == "capped"


def test_resolve_reconciled_requires_final_status(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    store.mark_cap_reconciliation_required("decap-1", "uncertain")

    with pytest.raises(CapStateError, match="final_status"):
        store.resolve_cap_operation("decap-1", "partial", detail="manual check")

    store.resolve_cap_operation(
        "decap-1", "partial", detail="manual check", final_status="uncapped",
    )
    assert store.get_cap_state(state_id, "stock", "") == "uncapped"


def test_operation_not_found_raises(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    _create_state(store, deck_path, deck)

    with pytest.raises(CapStateNotFoundError):
        store.mark_cap_reconciliation_required("does-not-exist", "detail")


# ── Durable state across restart ────────────────────────────────────────


def test_cap_state_survives_reopening_the_store(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    db_path = tmp_path / "state.db"
    store = DataStore(db_path)
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)
    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    store.complete_cap_operation("decap-1")
    store.close()

    reopened = DataStore(db_path)
    assert reopened.get_cap_state(state_id, "stock", "") == "uncapped"
    reopened.close()


def test_conflict_error_when_container_changed_out_of_band(tmp_path):
    deck_path, deck = _write_deck(tmp_path)
    store = DataStore(":memory:")
    state_id = _create_state(store, deck_path, deck)
    campaign_id = _create_linked_campaign(store, state_id)

    store.begin_cap_operation(state_id, "decap-1", "decap", "stock", "", campaign_id=campaign_id)
    # Simulate an out-of-band container mutation between begin and complete.
    store._conn.execute(
        "UPDATE cap_containers SET status = 'reconciliation_required', "
        "version = version + 1 WHERE labware_key = 'stock'"
    )
    store._conn.commit()
    with pytest.raises(CapStateConflictError):
        store.complete_cap_operation("decap-1")
