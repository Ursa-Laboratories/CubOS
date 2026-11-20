"""Resuming a part-applied multi-stroke transfer must preflight only what is left."""

from __future__ import annotations

import pytest

from cubos.instruments.pipette.exceptions import PipetteCommandError

from .harness import Fault, build_env, operator_reconcile
from .scenarios import PICK

BIG_STOCK = {"stock": {"volume_ul": 4000.0, "composition": {"water": 4000.0}}}


def _crash_midway(tmp_path, volume_ul, *, initial=None, kind="sim", crash_stroke=8):
    env = build_env(tmp_path, kind=kind, initial=initial or BIG_STOCK)
    assert env.run(PICK) is None
    env.faults.arm(Fault(
        "pipette.dispense", lambda: PipetteCommandError("lost acknowledgement"),
        crash_stroke, "after",
    ))
    transfer = ("transfer", {"source": "stock", "destination": "dest", "volume_ul": volume_ul})
    assert env.run(PICK, transfer) is not None
    operator_reconcile(env)
    env.restart()
    return env, transfer


def test_resume_near_destination_capacity_applies_only_the_remaining_strokes(tmp_path):
    env, transfer = _crash_midway(tmp_path, 1400.0)
    applied = env.durable_volumes()["dest"]
    assert 0 < applied < 1400.0

    assert env.run(PICK, transfer) is None

    assert env.durable_volumes()["dest"] == pytest.approx(1400.0)
    assert env.world.volumes["dest"] == pytest.approx(1400.0)
    assert env.durable_volumes()["stock"] == pytest.approx(2600.0)
    assert env.world.loaded_ul == 0.0


def test_resume_near_source_dead_volume_applies_only_the_remaining_strokes(tmp_path):
    initial = {"stock": {"volume_ul": 1550.0, "composition": {"water": 1550.0}}}
    env, transfer = _crash_midway(tmp_path, 1400.0, initial=initial)

    assert env.run(PICK, transfer) is None

    assert env.durable_volumes()["stock"] == pytest.approx(150.0)
    assert env.durable_volumes()["dest"] == pytest.approx(1400.0)


def test_resume_still_rejects_when_the_remainder_does_not_fit(tmp_path):
    env, transfer = _crash_midway(tmp_path, 1400.0)
    env.store.seed_fluid(env.state_id, env.deck.resolve_labware_target("dest"), 1000.0, {"water": 1000.0})
    env.world.volumes["dest"] = 1000.0
    ledger_before = len(env.pipette.ledger)

    error = env.run(PICK, transfer)

    assert error is not None and "exceeds its 1500 uL working volume" in str(error)
    assert len(env.pipette.ledger) == ledger_before


def test_replaying_a_fully_applied_transfer_is_a_no_op(tmp_path):
    env = build_env(tmp_path, initial=BIG_STOCK)
    transfer = ("transfer", {"source": "stock", "destination": "dest", "volume_ul": 1400.0})
    assert env.run(PICK, transfer) is None
    env.restart()
    assert env.run(PICK, transfer) is None
    assert env.durable_volumes()["dest"] == pytest.approx(1400.0)
    assert env.pipette.ledger == []


def _fail_applied_lookup(env, monkeypatch, exc):
    import sys

    original = env.store.get_fluid_snapshot

    def snapshot(*args, **kwargs):
        if sys._getframe(1).f_code.co_name == "_applied_stroke_volume":
            raise exc
        return original(*args, **kwargs)

    monkeypatch.setattr(env.store, "get_fluid_snapshot", snapshot)


def test_unreadable_applied_strokes_fall_back_to_preflighting_the_full_volume(
    tmp_path, monkeypatch, caplog,
):
    import logging
    import sqlite3

    env, transfer = _crash_midway(tmp_path, 1400.0)
    applied = env.durable_volumes()["dest"]
    assert 0 < applied < 1400.0
    _fail_applied_lookup(env, monkeypatch, sqlite3.OperationalError("database is locked"))
    ledger_before = len(env.pipette.ledger)

    with caplog.at_level(logging.DEBUG, logger="cubos.protocol_engine.commands.pipette"):
        error = env.run(PICK, transfer)

    assert error is not None and "exceeds its 1500 uL working volume" in str(error)
    assert len(env.pipette.ledger) == ledger_before
    records = [r for r in caplog.records if "full volume" in r.getMessage()]
    assert records and records[0].exc_info and "OperationalError" in records[0].getMessage()


def test_unexpected_errors_reading_applied_strokes_are_not_swallowed(
    tmp_path, monkeypatch,
):
    env, transfer = _crash_midway(tmp_path, 1400.0)
    _fail_applied_lookup(env, monkeypatch, RuntimeError("unexpected"))

    error = env.run(PICK, transfer)

    assert isinstance(error, RuntimeError) and str(error) == "unexpected"


def test_stroke_keys_checked_on_resume_are_the_keys_strokes_execute_under(tmp_path):
    env, transfer = _crash_midway(tmp_path, 1400.0)
    operations = env.store.get_fluid_snapshot(env.state_id)["operations"]
    applied = sorted(
        op["operation_key"] for op in operations
        if op["status"] == "applied" and ":stroke" in op["operation_key"]
    )
    from cubos.protocol_engine.commands.pipette import _stroke_substep

    assert applied
    substeps = {key.split(":substep:", 1)[1].rsplit(":transfer", 1)[0] for key in applied}
    assert substeps <= {_stroke_substep(None, i, 20) for i in range(20)}
    assert _stroke_substep(None, 3, 5) == "stroke3"
    assert _stroke_substep("outer", 3, 5) == "outer:stroke3"
    assert _stroke_substep("outer", 0, 1) == "outer"
