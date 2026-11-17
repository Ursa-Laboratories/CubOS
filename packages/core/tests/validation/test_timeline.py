from __future__ import annotations

import json
from pathlib import Path

import pytest

from cubos.validation.fluid_volumes import validate_protocol_fluid_volumes
from cubos.validation.timeline import TimingModel, simulate_protocol, simulate_setup

from .test_fluid_volumes import P300, SEED, _deck, _protocol

REPO = Path(__file__).resolve().parents[4]
PANDA = REPO / "packages/core/configs"


def _steps(*extra):
    return [
        ("pick_up_tip", {"position": "source"}),
        *extra,
        ("drop_tip", {"position": "dest"}),
    ]


def test_volumes_tracked_after_each_step_and_match_validator():
    protocol = _protocol(*_steps(
        ("aspirate", {"position": "source", "volume_ul": 200.0}),
        ("dispense", {"position": "dest", "volume_ul": 150.0}),
    ))
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    asp, disp = tl.steps[1], tl.steps[2]
    assert asp.loaded_ul == 200.0
    assert asp.volumes_ul["source"] == 800.0
    assert disp.loaded_ul == 50.0
    assert disp.volumes_ul["dest"] == 150.0
    assert disp.changed_ul == {"dest": 150.0}
    assert tl.initial_volumes_ul == {"source": 1000.0}
    assert tl.final_volumes_ul["source"] == 800.0
    assert any("holding 50" in w for w in tl.steps[3].warnings)
    assert not tl.ok


def test_transfer_projection_agrees_with_fluid_volume_validator():
    protocol = _protocol(
        *_steps(("transfer", {"source": "source", "destination": "dest", "volume_ul": 250.0}))
    )
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    assert tl.final_volumes_ul["source"] == 750.0
    assert tl.final_volumes_ul["dest"] == 250.0
    assert tl.violations == tuple(validate_protocol_fluid_volumes(protocol, _deck(), SEED, P300))
    assert tl.ok


def test_violations_surface_without_stopping_the_timeline():
    protocol = _protocol(
        *_steps(("transfer", {"source": "source", "destination": "dest", "volume_ul": 990.0}))
    )
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    assert tl.violations
    assert len(tl.steps) == 3
    assert not tl.ok


def test_without_initial_fluids_volumes_are_not_tracked_but_tips_and_time_are():
    protocol = _protocol(
        *_steps(("transfer", {"source": "source", "destination": "dest", "volume_ul": 100.0}))
    )
    tl = simulate_protocol(protocol, _deck(), pipette_config=P300)
    assert tl.initial_volumes_ul is None and tl.final_volumes_ul is None
    assert all(step.volumes_ul is None for step in tl.steps)
    assert tl.tips_used == 1
    assert tl.total_duration_s > 0


def test_tip_state_warnings():
    protocol = _protocol(
        ("aspirate", {"position": "source", "volume_ul": 10.0}),
        ("pick_up_tip", {"position": "source"}),
        ("pick_up_tip", {"position": "source"}),
        ("drop_tip", {"position": "dest"}),
        ("drop_tip", {"position": "dest"}),
    )
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    messages = [w for step in tl.steps for w in step.warnings]
    assert any("no tip attached" in m and "aspirate" in m for m in messages)
    assert any("already attached" in m for m in messages)
    assert any(m.startswith("drop_tip with no tip") for m in messages)
    assert tl.tips_used == 2


def test_blowout_and_multi_dispense_move_held_liquid():
    protocol = _protocol(*_steps(
        ("aspirate", {"position": "source", "volume_ul": 100.0}),
        ("blowout", {"position": "dest"}),
    ))
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    assert tl.steps[2].loaded_ul == 0.0
    assert tl.final_volumes_ul["dest"] == 100.0

    multi = _protocol(*_steps((
        "multi_dispense",
        {"source": "source", "destinations": ["dest", "plate.A1"], "volumes": [30.0, 20.0]},
    )))
    tl = simulate_protocol(multi, _deck(), initial_fluids=SEED, pipette_config=P300)
    assert tl.final_volumes_ul["source"] == 950.0
    assert tl.final_volumes_ul["dest"] == 30.0
    assert tl.final_volumes_ul["plate.A1"] == 20.0


def test_transfer_and_mix_are_projected_and_timed():
    protocol = _protocol(*_steps(
        ("transfer", {"source": "source", "destination": "plate.A1", "volume_ul": 50.0}),
        ("mix", {"position": "plate.A1", "volume_ul": 20.0, "cycles": 2}),
    ))
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    assert tl.final_volumes_ul["plate.A1"] == 50.0
    assert tl.steps[3].duration_s > 0
    assert not tl.unmodeled_commands


def test_duration_scales_with_timing_model_and_is_cumulative():
    protocol = _protocol(*_steps(
        ("aspirate", {"position": "source", "volume_ul": 100.0}),
        ("dispense", {"position": "dest", "volume_ul": 100.0}),
    ))
    slow = simulate_protocol(protocol, _deck(), pipette_config=P300,
                             timing=TimingModel(travel_mm_per_s=5.0))
    fast = simulate_protocol(protocol, _deck(), pipette_config=P300,
                             timing=TimingModel(travel_mm_per_s=500.0))
    assert slow.total_duration_s > fast.total_duration_s
    starts = [s.start_s for s in slow.steps]
    assert starts == sorted(starts)
    assert slow.steps[-1].start_s + slow.steps[-1].duration_s == pytest.approx(
        slow.total_duration_s
    )


def test_safe_z_adds_lift_travel():
    protocol = _protocol(*_steps(
        ("aspirate", {"position": "source", "volume_ul": 10.0}),
        ("dispense", {"position": "dest", "volume_ul": 10.0}),
    ))
    flat = simulate_protocol(protocol, _deck(), pipette_config=P300)
    lifted = simulate_protocol(protocol, _deck(), pipette_config=P300, safe_z=200.0)
    assert lifted.total_duration_s > flat.total_duration_s


def test_unresolvable_target_uses_fallback_and_unknown_command_is_flagged():
    protocol = _protocol(
        ("pick_up_tip", {"position": "nowhere"}),
        ("drop_tip", {"position": "dest"}),
    )
    tl = simulate_protocol(protocol, _deck(), pipette_config=P300)
    assert tl.steps[0].duration_s >= TimingModel().unknown_leg_travel_s
    assert tl.steps[1].duration_s > 0


def test_pause_and_home_durations():
    protocol = _protocol(
        ("home", {}),
        ("pause", {"seconds": 12.5}),
        ("pipette_home", {}),
    )
    tl = simulate_protocol(protocol, _deck(), pipette_config=P300)
    assert tl.steps[1].duration_s == 12.5
    assert tl.steps[0].duration_s == TimingModel().gantry_home_s


def test_to_dict_is_json_serialisable():
    protocol = _protocol(*_steps(
        ("transfer", {"source": "source", "destination": "dest", "volume_ul": 100.0}),
    ))
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    data = json.loads(json.dumps(tl.to_dict()))
    assert data["tips_used"] == 1
    assert data["steps"][1]["command"] == "transfer"
    assert data["assumptions"]


def test_simulate_setup_on_shipped_panda_configs():
    tl = simulate_setup(
        PANDA / "gantry/cub_xl_panda_pipetting_mock.yaml",
        PANDA / "deck/panda_imported_deck_pipetting_mock.yaml",
        PANDA / "protocol/panda/vial_transfer_acceptance.yaml",
        PANDA / "deck/panda_initial_fluids.yaml",
    )
    assert tl.tips_used == 1
    assert tl.tips_available > 1
    assert not tl.violations
    assert tl.steps[2].changed_ul
    assert tl.total_duration_s > 0


def _compound(name, args, seed=None):
    from .test_fluid_volumes import ROLE_SEED, _role_deck

    protocol = _protocol(
        ("pick_up_tip", {"position": "plate.A1"}),
        (name, args),
        ("drop_tip", {"position": "plate.A1"}),
    )
    return simulate_protocol(
        protocol, _role_deck(), initial_fluids=seed or ROLE_SEED, pipette_config=P300,
    )


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("rinse_well", {"well": "plate.A1", "volume_ul": 50.0, "cycles": 2,
                        "solution": "water"}),
        ("rinse_well", {"well": "plate.A1", "volume_ul": 50.0, "cycles": 1,
                        "solution": "water", "mix_repetitions": 2}),
        ("flush_pipette", {"volume_ul": 50.0, "cycles": 2, "solution": "water"}),
        ("purge_pipette", {"volume_ul": 50.0, "solution": "water"}),
    ],
)
def test_compound_commands_are_projected_and_timed(name, args):
    tl = _compound(name, args)
    assert tl.steps[1].duration_s > 0
    assert name not in tl.unmodeled_commands
    assert not tl.violations
    assert tl.steps[1].loaded_ul == 0.0


def test_compound_violation_is_collected_from_shared_projection():
    from .test_fluid_volumes import ROLE_SEED

    tl = _compound(
        "rinse_well",
        {"well": "plate.A1", "volume_ul": 60.0, "cycles": 1, "solution": "acetone"},
        seed=ROLE_SEED,
    )
    assert len(tl.violations) == 1


def test_serial_transfer_timeline_updates_each_well():
    protocol = _protocol(*_steps(
        ("serial_transfer", {"source": "source", "plate": "plate", "axis": "A",
                             "volumes": [100.0, 50.0]}),
    ))
    tl = simulate_protocol(protocol, _deck(), initial_fluids=SEED, pipette_config=P300)
    assert tl.final_volumes_ul["plate.A1"] == 100.0
    assert tl.final_volumes_ul["plate.A2"] == 50.0
    assert tl.steps[1].duration_s > 0


def test_split_transfer_costs_every_stroke():
    one = _protocol(*_steps(
        ("transfer", {"source": "source", "destination": "dest", "volume_ul": 250.0}),
    ))
    two = _protocol(*_steps(
        ("transfer", {"source": "source", "destination": "dest", "volume_ul": 100.0}),
    ))
    long = simulate_protocol(one, _deck(), pipette_config=P300)
    short = simulate_protocol(two, _deck(), pipette_config=P300)
    assert long.steps[1].duration_s > 2 * short.steps[1].duration_s


def test_pipette_home_duration():
    protocol = _protocol(("pick_up_tip", {"position": "source"}), ("pipette_home", {}))
    tl = simulate_protocol(protocol, _deck(), pipette_config=P300)
    assert tl.steps[1].duration_s == TimingModel().pipette_home_s


def test_transfer_prewet_and_dwell_lengthen_the_estimate():
    plain = _protocol(*_steps(
        ("transfer", {"source": "source", "destination": "dest", "volume_ul": 100.0}),
    ))
    extra = _protocol(*_steps((
        "transfer",
        {"source": "source", "destination": "dest", "volume_ul": 100.0,
         "prewet_cycles": 2, "aspirate_dwell_s": 3.0, "dispense_dwell_s": 2.0},
    )))
    base = simulate_protocol(plain, _deck(), pipette_config=P300).steps[1].duration_s
    longer = simulate_protocol(extra, _deck(), pipette_config=P300).steps[1].duration_s
    assert longer == pytest.approx(base + 5.0 + 4 * TimingModel().plunger_s(100.0, 50.0, 200.0))
