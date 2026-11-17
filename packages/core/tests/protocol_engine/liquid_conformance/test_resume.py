"""A run that crashes and is resumed must move each liquid exactly once."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cubos.instruments.pipette.exceptions import PipetteCommandError

from .harness import (
    PIPETTE_KINDS,
    Fault,
    assert_tips_match_durable,
    assert_world_matches_durable,
    build_env,
    operator_reconcile,
)
from .scenarios import fault_points, scenarios_for


def _clean_final_volumes(scenario, kind):
    with tempfile.TemporaryDirectory() as directory:
        env = build_env(Path(directory), kind=kind)
        assert env.run(*scenario.setup, *scenario.steps) is None
        return env.durable_volumes()


def _cases():
    cases = []
    for kind in PIPETTE_KINDS:
        for scenario in scenarios_for(kind):
            if True not in scenario.tracked_modes:
                continue
            for site, nth in fault_points(scenario, kind, True):
                if not site.startswith("pipette"):
                    continue
                cases.append(pytest.param(
                    kind, scenario, site, nth, id=f"{kind}-{scenario.name}-{site}#{nth}",
                ))
    return cases


@pytest.mark.parametrize("kind,scenario,site,nth", _cases())
def test_resume_never_double_applies(tmp_path, kind, scenario, site, nth):
    expected = _clean_final_volumes(scenario, kind)
    env = build_env(tmp_path, kind=kind)
    steps = (*scenario.setup, *scenario.steps)
    env.faults.arm(Fault(
        site, lambda: PipetteCommandError("lost acknowledgement"),
        nth + env.faults.calls.get(site, 0) + _setup_calls(kind, scenario, site), "after",
    ))
    assert env.run(*steps) is not None

    operator_reconcile(env)
    env.restart()
    before = env.durable_volumes()
    resumed = env.run(*steps)

    assert_world_matches_durable(env)
    assert_tips_match_durable(env)
    if resumed is None:
        assert env.durable_volumes() == pytest.approx(expected, abs=1e-6)
        assert env.world.volumes == pytest.approx(expected, abs=1e-6)
    else:
        for target, volume in env.durable_volumes().items():
            assert volume <= max(before[target], expected[target]) + 1e-6, (
                f"{target} rose to {volume:g} uL after a failed resume"
            )


def _setup_calls(kind, scenario, site):
    """Calls to *site* made by the scenario's setup steps on a clean run."""
    with tempfile.TemporaryDirectory() as directory:
        env = build_env(Path(directory), kind=kind)
        assert env.run(*scenario.setup) is None
        return env.faults.calls.get(site, 0)
