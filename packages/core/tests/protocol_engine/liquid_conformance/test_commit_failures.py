"""A failed journal commit after the physical action must demand reconciliation."""

from __future__ import annotations

import sqlite3

import pytest

from cubos.protocol_engine.errors import ProtocolExecutionError

from .harness import (
    assert_no_started_left,
    assert_tips_match_durable,
    assert_world_matches_durable,
    build_env,
    operator_reconcile,
)
from .scenarios import DROP, PICK

TRANSFER = ("transfer", {"source": "stock", "destination": "dest", "volume_ul": 30.0})
MIX = ("mix", {"position": "dest", "volume_ul": 20.0, "cycles": 1})


@pytest.mark.parametrize(
    "method,setup,step",
    [
        ("complete_fluid_transfer", (PICK,), TRANSFER),
        ("complete_fluid_mix", (PICK, TRANSFER), MIX),
        ("complete_pick_up_tip", (), PICK),
        ("complete_drop_tip", (PICK,), DROP),
    ],
)
def test_commit_failure_after_physical_success_is_flagged(tmp_path, monkeypatch, method, setup, step):
    env = build_env(tmp_path)
    assert env.run(*setup) is None

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(env.store, method, fail)
    error = env.run(step)

    assert isinstance(error, ProtocolExecutionError)
    assert "Reconciliation is required" in str(error)
    assert isinstance(error.__cause__, sqlite3.OperationalError)
    assert_no_started_left(env)
    assert env.pending_fluid() or env.pending_tip()
    assert_world_matches_durable(env)
    assert_tips_match_durable(env)

    monkeypatch.undo()
    operator_reconcile(env)
    assert not env.pending_fluid() and not env.pending_tip()
    assert_world_matches_durable(env)
    assert_tips_match_durable(env)
