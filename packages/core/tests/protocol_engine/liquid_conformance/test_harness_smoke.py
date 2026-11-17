"""The harness itself: a clean run keeps durable state and the world in step."""

from __future__ import annotations

import pytest

from cubos.instruments.pipette.exceptions import PipetteCommandError

from .harness import (
    PIPETTE_KINDS,
    Fault,
    StrictSimPipette,
    assert_tips_match_durable,
    assert_world_matches_durable,
    build_env,
)

PICK = ("pick_up_tip", {"position": "tip_rack.A1"})
DROP = ("drop_tip", {"position": "tip_disposal.discard"})


@pytest.mark.parametrize("kind", PIPETTE_KINDS)
@pytest.mark.parametrize("tracked", [True, False])
def test_clean_transfer_moves_exactly_the_requested_volume(tmp_path, kind, tracked):
    env = build_env(tmp_path, kind=kind, tracked=tracked)
    error = env.run(
        PICK,
        ("transfer", {"source": "stock", "destination": "dest", "volume_ul": 60.0}),
        DROP,
    )
    assert error is None
    assert env.world.volumes["stock"] == pytest.approx(1940.0)
    assert env.world.volumes["dest"] == pytest.approx(60.0)
    assert env.world.loaded_ul == 0.0
    if tracked:
        assert env.durable_volumes()["dest"] == pytest.approx(60.0)
        assert_world_matches_durable(env)
        assert_tips_match_durable(env)
        assert env.pending_fluid() == [] and env.pending_tip() == []


def test_strict_sim_rejects_what_the_vendor_drivers_tolerate(tmp_path):
    pipette = StrictSimPipette()
    with pytest.raises(PipetteCommandError, match="without a tip"):
        pipette.aspirate(10.0)
    pipette.pick_up_tip()
    with pytest.raises(PipetteCommandError, match="already attached"):
        pipette.pick_up_tip()
    pipette.aspirate(10.0)
    with pytest.raises(PipetteCommandError, match="only 10 uL held"):
        pipette.dispense(20.0)
    pipette.dispense(10.0)
    pipette.aspirate(10.0)
    assert pipette.aspirate(10.04).volume_ul == 10.0
    with pytest.raises(PipetteCommandError, match="outside"):
        pipette.aspirate(500.0)
    with pytest.raises(PipetteCommandError, match="holding liquid"):
        pipette.home()
    pipette.blowout()
    assert pipette.loaded_volume_ul == 0.0
    pipette.drop_tip()
    with pytest.raises(PipetteCommandError, match="blowout without"):
        pipette.blowout()


def test_fault_plan_fires_once_on_the_requested_call(tmp_path):
    boom = PipetteCommandError("boom")
    env = build_env(
        tmp_path, faults=[Fault("pipette.aspirate", lambda: boom, nth=2)], tracked=False,
    )
    env.run(PICK)
    assert env.run(
        ("transfer", {"source": "stock", "destination": "dest", "volume_ul": 20.0}),
    ) is None
    error = env.run(
        ("transfer", {"source": "stock", "destination": "dest", "volume_ul": 20.0}),
    )
    assert error is boom
    assert env.faults.fired and env.faults.calls["pipette.aspirate"] == 2
