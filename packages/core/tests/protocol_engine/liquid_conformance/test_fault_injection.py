"""Fault injection across every liquid command, vendor driver and call site.

For each command the clean run is traced to find every gantry and pipette call;
each call is then failed in turn, both before its physical effect and after it
(a lost acknowledgement). Whatever the failure, the durable journal must stay
honest about the physical world and the original exception must reach the caller.
"""

from __future__ import annotations

import pytest

from cubos.gantry.gantry_driver.exceptions import MillConnectionError, StatusReturnError
from cubos.instruments.pipette.exceptions import PipetteCommandError, PipetteTimeoutError

from .harness import (
    PIPETTE_KINDS,
    Fault,
    assert_no_started_left,
    assert_tips_match_durable,
    assert_world_matches_durable,
    build_env,
)
from .scenarios import fault_points, scenarios_for

PIPETTE_ERRORS = (
    lambda: PipetteCommandError("injected driver error"),
    lambda: PipetteTimeoutError("injected timeout"),
    lambda: KeyboardInterrupt(),
)
GANTRY_ERRORS = (
    lambda: StatusReturnError("injected alarm"),
    lambda: MillConnectionError("injected connection loss"),
    lambda: KeyboardInterrupt(),
)


def _cases():
    cases = []
    for kind in PIPETTE_KINDS:
        for scenario in scenarios_for(kind):
            for tracked in scenario.tracked_modes:
                for index, (site, nth) in enumerate(fault_points(scenario, kind, tracked)):
                    if kind != "sim" and not site.startswith("pipette"):
                        continue
                    errors = PIPETTE_ERRORS if site.startswith("pipette") else GANTRY_ERRORS
                    for phase in ("before", "after"):
                        cases.append(pytest.param(
                            kind, scenario, tracked, site, nth, phase,
                            errors[(index + (phase == "after")) % len(errors)],
                            id=f"{kind}-{scenario.name}-{'tracked' if tracked else 'untracked'}"
                               f"-{site}#{nth}-{phase}",
                        ))
    return cases


@pytest.mark.parametrize("kind,scenario,tracked,site,nth,phase,error", _cases())
def test_failure_leaves_an_honest_journal(tmp_path, kind, scenario, tracked, site, nth, phase, error):
    env = build_env(tmp_path, kind=kind, tracked=tracked)
    assert env.run(*scenario.setup) is None
    env.faults.arm(Fault(site, error, nth, phase))
    moves_before = len(env.gantry.moves)

    raised = env.run(*scenario.steps)

    assert env.faults.fired, "fault point was never reached"
    assert raised is env.faults.raised, (
        f"{site} raised {type(env.faults.raised).__name__} but the command surfaced {raised!r}"
    )
    assert abs(env.world.total() - env.world.initial_total) <= 1e-4
    if not tracked:
        return

    assert_no_started_left(env)
    assert_world_matches_durable(env)
    assert_tips_match_durable(env)
    if env.world.loaded_ul > 1e-6:
        assert env.pending_fluid() or env.pending_tip(), (
            f"{env.world.loaded_ul:g} uL is stranded in the tip with no pending operation"
        )

    if env.pending_fluid() or env.pending_tip():
        env.faults.faults.clear()
        calls_before = dict(env.faults.calls)
        blocked = env.run(
            ("transfer", {"source": "stock", "destination": "dest", "volume_ul": 30.0}),
        )
        assert blocked is not None, "liquid handling continued past an unreconciled operation"
        assert env.faults.calls.get("pipette.aspirate", 0) == calls_before.get("pipette.aspirate", 0)
    assert len(env.gantry.moves) >= moves_before
