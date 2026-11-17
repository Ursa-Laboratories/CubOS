from __future__ import annotations

import pytest

from cubos.protocol_engine.builder import ProtocolBuilder
from cubos.protocol_engine.commands import pipette as commands

from .liquid_conformance.harness import build_env
from .liquid_conformance.scenarios import PICK

BASE = {"source": "stock", "destination": "dest", "volume_ul": 30.0}


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(commands, "_sleep", calls.append)
    return calls


@pytest.mark.parametrize("tracked", [True, False])
def test_prewet_and_dwell_order_and_net_liquid(tmp_path, sleeps, tracked):
    env = build_env(tmp_path, tracked=tracked)
    assert env.run(PICK) is None
    ledger_start = len(env.pipette.ledger)
    args = {**BASE, "prewet_cycles": 2, "aspirate_dwell_s": 1.5, "dispense_dwell_s": 0.5}

    assert env.run(("transfer", args)) is None

    moves = [(kind, volume) for kind, volume, _ in env.pipette.ledger[ledger_start:]]
    assert moves == [
        ("aspirate", 30.0), ("dispense", 30.0),
        ("aspirate", 30.0), ("dispense", 30.0),
        ("aspirate", 30.0), ("dispense", 30.0), ("blowout", 0.0),
    ]
    assert sleeps == [1.5, 0.5]
    assert env.world.volumes["dest"] == pytest.approx(30.0)
    assert env.world.volumes["stock"] == pytest.approx(1970.0)
    if tracked:
        assert env.durable_volumes()["dest"] == pytest.approx(30.0)


def test_defaults_add_no_pipette_calls_or_sleeps(tmp_path, sleeps):
    env = build_env(tmp_path)
    assert env.run(PICK) is None
    start = len(env.pipette.ledger)
    assert env.run(("transfer", BASE)) is None
    assert [m[0] for m in env.pipette.ledger[start:]] == ["aspirate", "dispense", "blowout"]
    assert sleeps == []


def test_each_stroke_of_a_split_transfer_is_prewet_and_dwelled(tmp_path, sleeps):
    env = build_env(tmp_path)
    assert env.run(PICK) is None
    args = {**BASE, "volume_ul": 150.0, "prewet_cycles": 1, "aspirate_dwell_s": 1.0}
    assert env.run(("transfer", args)) is None
    assert len(sleeps) == 2
    assert env.world.volumes["dest"] == pytest.approx(150.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prewet_cycles", -1), ("prewet_cycles", 6), ("prewet_cycles", 1.5),
        ("prewet_cycles", True), ("aspirate_dwell_s", -0.1), ("dispense_dwell_s", 601),
        ("aspirate_dwell_s", float("nan")), ("dispense_dwell_s", float("inf")),
    ],
)
def test_invalid_values_are_rejected_when_the_protocol_is_built(field, value):
    with pytest.raises(ValueError, match=field):
        ProtocolBuilder().add_command("transfer", **{**BASE, field: value}).build()


def test_summary_mentions_the_options():
    from cubos.protocol_engine.commands import _summaries

    text = _summaries.transfer({**BASE, "prewet_cycles": 2, "aspirate_dwell_s": 1.0})
    assert "prewet x2" in text and "dwell 1s/0s" in text
    assert "prewet" not in _summaries.transfer(BASE)
