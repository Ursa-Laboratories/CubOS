"""Property-style checks that liquid is conserved through planning and execution."""

from __future__ import annotations

import math
import random

import pytest

from cubos.instruments.pipette.models import PICUS2_MODELS, PIPETTE_MODELS, PipetteConfig
from cubos.instruments.pipette.liquid_class import LiquidClassCorrection
from cubos.protocol_engine.commands._liquid_transfer import (
    LiquidTransferPreflightError,
    plan_strokes,
)

from .harness import (
    SIM_CONFIG,
    assert_tips_match_durable,
    assert_world_matches_durable,
    build_env,
    durable_composition_totals,
)
from .scenarios import DROP, PICK

CONFIGS = [
    SIM_CONFIG,
    PICUS2_MODELS["picus2_1ch_10"],
    PICUS2_MODELS["picus2_1ch_120"],
    PICUS2_MODELS["picus2_1ch_1000"],
    PICUS2_MODELS["picus2_1ch_5000"],
    PIPETTE_MODELS["p300_single_gen2"],
    PIPETTE_MODELS["flex_1channel_1000"],
]


@pytest.mark.parametrize("config", CONFIGS, ids=lambda c: c.name)
def test_planned_strokes_conserve_volume_and_respect_model_bounds(config: PipetteConfig):
    rng = random.Random(f"strokes-{config.name}")
    planned = 0
    for _ in range(400):
        volume = rng.uniform(config.min_volume * 0.5, config.max_volume * 12)
        correction = None
        if rng.random() < 0.5:
            correction = LiquidClassCorrection(
                multiplier=rng.uniform(0.9, 1.15), offset_ul=rng.uniform(-1.0, 1.0),
            )
        try:
            strokes = plan_strokes(volume, config, correction)
        except LiquidTransferPreflightError:
            continue
        planned += 1
        assert math.fsum(strokes) == pytest.approx(volume, abs=1e-9)
        for stroke in strokes:
            commanded = correction.apply(stroke) if correction else stroke
            assert config.min_volume - 1e-6 <= stroke
            assert config.min_volume - 1e-6 <= commanded <= config.max_volume + 1e-6
        assert max(strokes) - min(strokes) <= 1e-6 + max(strokes) / len(strokes) * 1e-6 * len(strokes)
    assert planned > 200


def _exact_volume(rng: random.Random) -> float:
    """A volume whose equal strokes are exact multiples of the 0.1 uL increment."""
    count = rng.choice([1, 1, 2, 3])
    low = 5.0 if count == 1 else 100.0 * (count - 1) / count + 0.1
    stroke = round(rng.uniform(low, 100.0), 1)
    return round(count * stroke, 1)


WORKING_UL = {"stock": 4500.0, "dest": 1500.0, "waste": 4500.0, "plate.A1": 300.0,
              "plate.B2": 300.0, "plate.A3": 300.0}
DEAD_UL = {"stock": 100.0}


def _next_transfer(rng: random.Random, durable: dict[str, float]):
    """A random transfer that mostly fits and sometimes deliberately overreaches."""
    while True:
        source, destination = rng.sample(sorted(WORKING_UL), 2)
        available = durable[source] - DEAD_UL.get(source, 0.0)
        room = WORKING_UL[destination] - durable[destination]
        limit = min(available, room)
        if limit >= 5.0:
            break
    if rng.random() < 0.2:
        return source, destination, _exact_volume(rng)
    cap = min(limit, 100.0)
    return source, destination, round(rng.uniform(5.0, cap), 1)


@pytest.mark.parametrize("seed", range(6))
def test_random_transfer_sequences_keep_durable_state_equal_to_the_world(tmp_path, seed):
    rng = random.Random(seed)
    initial = {"stock": {"volume_ul": 3000.0, "composition": {"water": 3000.0}}}
    env = build_env(tmp_path, kind="sim", initial=initial)
    assert env.run(PICK) is None
    accepted = rejected = 0
    for _ in range(40):
        source, destination, volume = _next_transfer(rng, env.durable_volumes())
        before_world = dict(env.world.volumes)
        before_ledger = len(env.pipette.ledger)
        env.next_campaign()

        error = env.run(
            ("transfer", {"source": source, "destination": destination, "volume_ul": volume}),
        )

        if error is None:
            accepted += 1
        else:
            rejected += 1
            assert len(env.pipette.ledger) == before_ledger, "rejected transfer still moved the tip"
            assert env.world.volumes == before_world
        assert_world_matches_durable(env)
        assert env.pending_fluid() == []
        assert env.world.loaded_ul == 0.0
        assert env.durable_volumes() == pytest.approx(env.world.volumes, abs=1e-6)
        assert durable_composition_totals(env)["water"] == pytest.approx(3000.0, abs=1e-4)
    assert accepted >= 20
    assert env.run(DROP) is None
    assert_tips_match_durable(env)


@pytest.mark.parametrize("volumes", [[20.0, 25.0, 30.0], [10.0, 10.0, 10.0], [50.0, 5.0, 95.0]])
def test_serial_transfer_moves_exactly_the_listed_volumes(tmp_path, volumes):
    env = build_env(tmp_path)
    assert env.run(PICK) is None
    error = env.run((
        "serial_transfer",
        {"source": "stock", "plate": "plate", "axis": "A", "volumes": volumes},
    ))
    assert error is None
    for well, volume in zip(["A1", "A2", "A3"], volumes):
        assert env.world.volumes[f"plate.{well}"] == pytest.approx(volume)
        assert env.durable_volumes()[f"plate.{well}"] == pytest.approx(volume)
    assert env.durable_volumes()["stock"] == pytest.approx(2000.0 - sum(volumes))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The fluid journal books the requested stroke volume while the Picus drivers "
        "move it rounded to the model increment, so a 33.33 uL request books 0.03 uL "
        "more than moved. Needs an owner decision: reject, snap, or book the moved volume."
    ),
)
@pytest.mark.parametrize("volume_ul", [33.33, 250.0 / 3 * 3 + 0.04])
def test_durable_bookkeeping_matches_what_a_quantizing_pipette_moves(tmp_path, volume_ul):
    env = build_env(tmp_path, kind="picus")
    assert env.run(PICK) is None
    assert env.run(
        ("transfer", {"source": "stock", "destination": "dest", "volume_ul": volume_ul}),
    ) is None
    assert env.durable_volumes()["dest"] == pytest.approx(env.world.volumes["dest"], abs=1e-6)
