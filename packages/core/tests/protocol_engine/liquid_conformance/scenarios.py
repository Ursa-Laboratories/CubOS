"""One scenario per liquid command, with the steps that precede it."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .harness import build_env

Step = tuple[str, dict[str, Any]]

PICK: Step = ("pick_up_tip", {"position": "tip_rack.A1"})
DROP: Step = ("drop_tip", {"position": "tip_disposal.discard"})


def multi_volume(kind: str) -> float:
    return {"sim": 150.0, "picus": 150.0, "opentrons": 250.0}[kind]


@dataclass(frozen=True)
class Scenario:
    name: str
    setup: tuple[Step, ...]
    steps: tuple[Step, ...]
    tracked_modes: tuple[bool, ...] = (True, False)


def _transfer(volume: float) -> Step:
    return ("transfer", {"source": "stock", "destination": "dest", "volume_ul": volume})


def scenarios(kind: str) -> list[Scenario]:
    return [
        Scenario("pick_up_tip", (), (PICK,)),
        Scenario("drop_tip", (PICK,), (DROP,)),
        Scenario(
            "aspirate", (PICK,),
            (("aspirate", {"position": "stock", "volume_ul": 30.0}),),
            tracked_modes=(False,),
        ),
        Scenario(
            "dispense",
            (PICK, ("aspirate", {"position": "stock", "volume_ul": 30.0})),
            (("dispense", {"position": "dest", "volume_ul": 30.0}),),
            tracked_modes=(False,),
        ),
        Scenario("blowout", (PICK,), (("blowout", {"position": "dest"}),)),
        Scenario("pipette_home", (PICK,), (("pipette_home", {}),)),
        Scenario(
            "mix", (PICK, _transfer(40.0)),
            (("mix", {"position": "dest", "volume_ul": 20.0, "cycles": 2}),),
        ),
        Scenario("transfer", (PICK,), (_transfer(30.0),)),
        Scenario("transfer_multi_stroke", (PICK,), (_transfer(multi_volume(kind)),)),
        Scenario(
            "serial_transfer", (PICK,),
            (("serial_transfer", {
                "source": "stock", "plate": "plate", "axis": "A",
                "volumes": [20.0, 25.0, 30.0],
            }),),
        ),
        Scenario(
            "multi_dispense", (PICK,),
            (("multi_dispense", {
                "source": "stock", "destinations": ["dest", "waste"],
                "volumes": [20.0, 30.0],
            }),),
            tracked_modes=(False,),
        ),
        Scenario(
            "rinse_well", (PICK,),
            (("rinse_well", {
                "well": "dest", "volume_ul": 20.0, "cycles": 2, "source": "stock",
                "waste": "waste", "mix_repetitions": 1,
            }),),
        ),
        Scenario(
            "flush_pipette", (PICK,),
            (("flush_pipette", {
                "volume_ul": 20.0, "cycles": 2, "source": "stock", "waste": "waste",
            }),),
        ),
        Scenario(
            "purge_pipette", (PICK,),
            (("purge_pipette", {"volume_ul": 20.0, "source": "stock", "waste": "waste"}),),
        ),
        Scenario(
            "clear_well", (PICK, _transfer(40.0)),
            (("clear_well", {"well": "dest", "waste": "waste", "volume_ul": 40.0}),),
        ),
    ]


LEGACY_VENDOR_SCENARIOS = frozenset(
    {"pick_up_tip", "drop_tip", "transfer", "transfer_multi_stroke", "mix"}
)


def scenarios_for(kind: str) -> list[Scenario]:
    """All scenarios for the primary targets; the legacy vendor gets a core subset."""
    if kind == "opentrons":
        return [s for s in scenarios(kind) if s.name in LEGACY_VENDOR_SCENARIOS]
    return scenarios(kind)


def fault_points(scenario: Scenario, kind: str, tracked: bool) -> list[tuple[str, int]]:
    """Every (site, nth) the scenario's steps reach on a clean run."""
    with tempfile.TemporaryDirectory() as directory:
        env = build_env(Path(directory), kind=kind, tracked=tracked)
        assert env.run(*scenario.setup) is None, scenario.name
        before = dict(env.faults.calls)
        assert env.run(*scenario.steps) is None, scenario.name
        after = env.faults.calls
        return [
            (site, nth)
            for site in sorted(after)
            for nth in range(1, after[site] - before.get(site, 0) + 1)
        ]
