"""Single-aspiration batches, using only offline pipettes and mocked motion."""

from dataclasses import replace
from unittest.mock import MagicMock, call

import pytest
from cubos.deck.deck import Deck
from cubos.deck.labware.labware import Coordinate3D
from cubos.deck.labware.vial import Vial
from cubos.gantry.errors import MillConnectionError
from cubos.instruments.pipette.exceptions import PipetteCommandError
from cubos.instruments.pipette.models import AspirateResult
from cubos.instruments.pipette.vendors.opentrons import OpentronsPipette
from cubos.instruments.pipette.vendors.sartorius import SartoriusPicus2Pipette
from cubos.protocol_engine.builder import ProtocolBuilder
from cubos.protocol_engine.commands.pipette import multi_dispense
from cubos.protocol_engine.errors import ProtocolExecutionError
from cubos.protocol_engine.registry import CommandRegistry
from cubos.protocol_engine.runtime import ProtocolContext
from pydantic import ValidationError


@pytest.fixture(params=["opentrons", "sartorius"])
def ctx(request, monkeypatch):
    def no_serial(*args, **kwargs):
        pytest.fail("Tests must not open a serial port")

    monkeypatch.setattr("serial.Serial", no_serial)
    if request.param == "opentrons":
        pipette = OpentronsPipette(pipette_model="p300_single_gen2", offline=True)
    else:
        pipette = SartoriusPicus2Pipette(pipette_model="picus2_1ch_120", offline=True)
    pipette.pick_up_tip()
    board = MagicMock()
    board.instruments = {"pipette": pipette}
    deck = Deck({
        name: Vial(
            name=name, height=20, diameter=10, capacity_ul=1000,
            working_volume_ul=800, location=Coordinate3D(x=x, y=50, z=20),
        )
        for name, x in [("source", 30), ("first", 50), ("second", 70)]
    })
    return ProtocolContext(gantry=board, deck=deck)


def run(ctx, **kwargs):
    args = {"source": "source", "destinations": ["first", "second"], "volumes": [40, 60]}
    args.update(kwargs)
    return multi_dispense(ctx, **args)


def test_one_aspiration_order_and_volume_bookkeeping(ctx, monkeypatch):
    pipette = ctx.gantry.instruments["pipette"]
    events = []
    ctx.gantry.move.side_effect = lambda tool, xyz: events.append(("move", xyz))
    for method in ["aspirate", "dispense", "blowout"]:
        original = getattr(pipette, method)

        def record(*args, method=method, original=original):
            result = original(*args)
            events.append((method, args, pipette.loaded_volume_ul))
            return result

        monkeypatch.setattr(pipette, method, record)
    run(ctx, source_height=-2, destination_height=3, speed=25)
    assert events == [
        ("move", (30, 50, 18)), ("aspirate", (100, 25), 100),
        ("move", (50, 50, 23)), ("dispense", (40, 25), 60),
        ("move", (70, 50, 23)), ("dispense", (60, 25), 0),
        ("blowout", (25,), 0),
    ]


@pytest.mark.parametrize("volumes", [[], [40], [0, 40], [-20, 40], [True, 40],
                                    [float("nan"), 40], [float("inf"), 40],
                                    [1, 40], [1000, 40], [100, 110]])
def test_invalid_batch_has_no_motion_or_actuation(ctx, volumes, monkeypatch):
    pipette = ctx.gantry.instruments["pipette"]
    aspirate = MagicMock(wraps=pipette.aspirate)
    monkeypatch.setattr(pipette, "aspirate", aspirate)
    with pytest.raises(ProtocolExecutionError):
        run(ctx, volumes=volumes)
    assert not ctx.gantry.mock_calls
    aspirate.assert_not_called()
    assert pipette.loaded_volume_ul == 0


def test_capacity_boundary(ctx):
    capacity = ctx.gantry.instruments["pipette"].config.max_volume
    run(ctx, volumes=[capacity / 2, capacity / 2])
    assert ctx.gantry.instruments["pipette"].loaded_volume_ul == 0


def test_increment_is_checked_before_aspiration(ctx):
    pipette = ctx.gantry.instruments["pipette"]
    pipette._config = replace(pipette.config, volume_increment_ul=0.1)
    with pytest.raises(ProtocolExecutionError, match="multiple of"):
        run(ctx, volumes=[40.04, 60.04])
    assert not ctx.gantry.mock_calls


@pytest.mark.parametrize("kwargs", [
    {"destinations": []}, {"destinations": ["first", "missing"]},
    {"speed": float("nan")}, {"speed": 101},
    {"source_height": float("inf")}, {"destination_height": True},
])
def test_bad_arguments_rejected_before_motion(ctx, kwargs):
    with pytest.raises(ProtocolExecutionError):
        run(ctx, **kwargs)
    assert not ctx.gantry.mock_calls


def test_loaded_pipette_rejected_without_motion(ctx):
    ctx.gantry.instruments["pipette"].aspirate(40)
    with pytest.raises(ProtocolExecutionError, match="known empty"):
        run(ctx)
    assert not ctx.gantry.mock_calls


def test_unknown_capacity_rejected(ctx):
    ctx.gantry.instruments["pipette"] = MagicMock(config=None)
    with pytest.raises(ProtocolExecutionError, match="model capacity"):
        run(ctx)
    assert not ctx.gantry.mock_calls


def test_unknown_volume_rejected(ctx):
    config = ctx.gantry.instruments["pipette"].config
    ctx.gantry.instruments["pipette"] = MagicMock(config=config, loaded_volume_ul=None)
    with pytest.raises(ProtocolExecutionError, match="known empty"):
        run(ctx)
    assert not ctx.gantry.mock_calls


def test_tracking_rejected_before_motion(ctx):
    ctx.fluid_state_id = 1
    ctx.campaign_id = 2
    ctx.data_store = MagicMock()
    with pytest.raises(ProtocolExecutionError, match="durable fluid tracking"):
        run(ctx)
    assert not ctx.gantry.mock_calls
    assert not ctx.data_store.mock_calls


def test_successful_portions_logged_individually(ctx):
    ctx.data_store = MagicMock()
    ctx.campaign_id = 12
    run(ctx)
    assert ctx.data_store.record_transfer.call_args_list == [
        call(12, "source", None, "first", None, 40),
        call(12, "source", None, "second", None, 60),
    ]


@pytest.mark.parametrize("failure", [PipetteCommandError("failure"), MillConnectionError("lost"), KeyboardInterrupt()])
def test_second_dispense_failure_stops_without_blowout_or_retry(ctx, monkeypatch, failure):
    pipette = ctx.gantry.instruments["pipette"]
    original = pipette.dispense
    calls = []

    def dispense(volume, speed):
        calls.append(volume)
        if len(calls) == 2:
            raise failure
        return original(volume, speed)

    monkeypatch.setattr(pipette, "dispense", dispense)
    blowout = MagicMock()
    monkeypatch.setattr(pipette, "blowout", blowout)
    ctx.data_store = MagicMock()
    ctx.campaign_id = 12
    with pytest.raises(type(failure)) as caught:
        run(ctx)
    assert caught.value is failure
    assert calls == [40, 60]
    assert pipette.loaded_volume_ul == 60
    blowout.assert_not_called()
    ctx.data_store.record_transfer.assert_called_once_with(12, "source", None, "first", None, 40)


@pytest.mark.parametrize("method", ["aspirate", "dispense"])
def test_unsuccessful_result_aborts(ctx, monkeypatch, method):
    pipette = ctx.gantry.instruments["pipette"]
    monkeypatch.setattr(pipette, method, MagicMock(return_value=AspirateResult(False, 0, 0)))
    blowout = MagicMock()
    monkeypatch.setattr(pipette, "blowout", blowout)
    with pytest.raises(ProtocolExecutionError, match="did not succeed"):
        run(ctx)
    blowout.assert_not_called()


def test_builder_and_schema_expose_command(ctx):
    protocol = ProtocolBuilder().add_command(
        "multi_dispense", source="source", destinations=["first", "second"], volumes=[40, 60],
    ).build()
    protocol.execute(ctx)
    registered = CommandRegistry.instance().get("multi_dispense")
    assert "one aspiration" in registered.describe(protocol.steps[0].args)
    with pytest.raises(ValidationError):
        registered.schema.model_validate({"source": "source", "destinations": ["first"], "volumes": [True]})


@pytest.mark.parametrize("stage", ["aspirate", "move", "blowout"])
def test_failure_propagates_without_repeating_any_action(ctx, monkeypatch, stage):
    pipette = ctx.gantry.instruments["pipette"]
    failure = MillConnectionError("connection lost")
    aspirate = MagicMock(wraps=pipette.aspirate)
    dispense = MagicMock(wraps=pipette.dispense)
    blowout = MagicMock(wraps=pipette.blowout)
    monkeypatch.setattr(pipette, "aspirate", aspirate)
    monkeypatch.setattr(pipette, "dispense", dispense)
    monkeypatch.setattr(pipette, "blowout", blowout)
    if stage == "move":
        ctx.gantry.move.side_effect = [None, failure]
    else:
        {"aspirate": aspirate, "blowout": blowout}[stage].side_effect = failure
    with pytest.raises(MillConnectionError) as caught:
        run(ctx)
    assert caught.value is failure
    assert aspirate.call_count == 1
    assert dispense.call_count == (2 if stage == "blowout" else 0)
    assert blowout.call_count == (1 if stage == "blowout" else 0)


def test_single_and_repeated_destinations(ctx):
    run(ctx, destinations=["first"], volumes=[40])
    run(ctx, destinations=["first", "first"], volumes=[40, 40])
    assert ctx.gantry.instruments["pipette"].loaded_volume_ul == 0


def test_missing_pipette_rejected_before_motion(ctx):
    ctx.gantry.instruments = {}
    with pytest.raises(ProtocolExecutionError, match="No pipette"):
        run(ctx)
    assert not ctx.gantry.mock_calls


def test_whole_microlitre_configuration_rejects_fractional_batch_before_motion(ctx):
    pipette = SartoriusPicus2Pipette(
        pipette_model="picus2_1ch_120", whole_microlitres_only=True, offline=True,
    )
    ctx.gantry.instruments["pipette"] = pipette
    assert pipette.config.volume_increment_ul == 1.0
    with pytest.raises(ProtocolExecutionError, match="multiple of 1"):
        run(ctx, volumes=[40.6, 50.6])
    assert not ctx.gantry.mock_calls
    assert pipette.loaded_volume_ul == 0
    run(ctx, volumes=[40, 50])
    assert pipette.loaded_volume_ul == 0


def test_fractional_portions_conserve_one_aspiration(ctx):
    pipette = SartoriusPicus2Pipette(pipette_model="picus2_1ch_120", offline=True)
    ctx.gantry.instruments["pipette"] = pipette
    run(ctx, volumes=[40.6, 50.6])
    assert pipette.loaded_volume_ul == 0
