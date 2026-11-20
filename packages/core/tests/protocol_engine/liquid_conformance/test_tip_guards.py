"""Tip bookkeeping guards that must hold before any motion."""

from __future__ import annotations

import pytest

from .harness import build_env
from .scenarios import DROP, PICK

SECOND_PICK = ("pick_up_tip", {"position": "tip_rack.A2"})


@pytest.mark.parametrize("tracked", [True, False])
def test_second_pick_up_without_a_drop_is_refused_before_motion(tmp_path, tracked):
    env = build_env(tmp_path, tracked=tracked)
    assert env.run(PICK) is None
    moves = len(env.gantry.moves)

    error = env.run(SECOND_PICK)

    assert error is not None
    assert len(env.gantry.moves) == moves
    assert env.world.tips["tip_rack.A2"] is True


def test_replaying_an_applied_pick_up_still_restores_the_attachment(tmp_path):
    env = build_env(tmp_path)
    assert env.run(PICK) is None
    env.restart()
    assert env.pipette.attached_tip_extension > 0
    assert env.run(PICK) is None
    assert env.run(DROP) is None
