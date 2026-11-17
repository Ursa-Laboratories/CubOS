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
