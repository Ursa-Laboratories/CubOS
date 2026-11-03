"""Repeat compilation, deck validation, and flat protocol compatibility."""

from types import SimpleNamespace

import pytest

from cubos.protocol_engine.compiler import (
    MAX_EXPANDED_PROTOCOL_STEPS,
    CommandCall,
    compile_protocol,
    expand_repeat_calls,
)


def _repeat_call(**updates):
    args = {
        "labware": "plate",
        "template_well": "A1",
        "wells": ["A1"],
        "steps": [{"move": {"instrument": "pipette", "position": "plate.A1"}}],
    }
    args.update(updates)
    return CommandCall("repeat", args)


def test_repeat_compile_substitutes_exact_targets_recursively():
    protocol = compile_protocol([_repeat_call(
        wells=["A1", "B2"],
        steps=[{"measure": {
            "instrument": "sensor",
            "position": "plate.A1",
            "measurement_height": 0.0,
            "method_kwargs": {
                "nested": ["plate.A1", ("plate.A1", "prefix plate.A1")],
            },
        }}],
    )])

    assert [step.args["position"] for step in protocol.steps] == [
        "plate.A1", "plate.B2",
    ]
    assert [step.args["method_kwargs"] for step in protocol.steps] == [
        {"nested": ["plate.A1", ("plate.A1", "prefix plate.A1")]},
        {"nested": ["plate.B2", ("plate.B2", "prefix plate.A1")]},
    ]


@pytest.mark.parametrize("error", [KeyError("plate"), ValueError("bad path")])
def test_repeat_deck_resolution_errors_are_reported(error):
    deck = SimpleNamespace(resolve_labware=lambda _path: (_ for _ in ()).throw(error))

    with pytest.raises(ValueError, match="cannot be resolved"):
        expand_repeat_calls([_repeat_call()], deck=deck)


def test_repeat_rejects_resolved_labware_without_wells():
    deck = SimpleNamespace(resolve_labware=lambda _path: SimpleNamespace(wells=None))

    with pytest.raises(ValueError, match="does not contain wells"):
        expand_repeat_calls([_repeat_call()], deck=deck)


def test_repeat_rejects_template_well_missing_from_resolved_labware():
    deck = SimpleNamespace(resolve_labware=lambda _path: SimpleNamespace(wells={"A1": object()}))

    with pytest.raises(ValueError, match="unknown well.*A2"):
        expand_repeat_calls([_repeat_call(template_well="A2")], deck=deck)


def test_repeat_expansion_limit_includes_following_flat_commands():
    calls = [_repeat_call()]
    calls.extend(
        CommandCall("move", {
            "instrument": "pipette", "position": "plate.A1",
        })
        for _ in range(MAX_EXPANDED_PROTOCOL_STEPS)
    )

    with pytest.raises(ValueError, match="maximum"):
        expand_repeat_calls(calls)


def test_flat_protocol_compilation_keeps_legacy_step_order_and_arguments():
    protocol = compile_protocol([
        CommandCall("move", {"instrument": "pipette", "position": "plate.A1"}),
        CommandCall("move", {"instrument": "pipette", "position": "plate.B1"}),
    ])

    assert [(step.command_name, step.args) for step in protocol.steps] == [
        ("move", {"instrument": "pipette", "position": "plate.A1"}),
        ("move", {"instrument": "pipette", "position": "plate.B1"}),
    ]


def test_flat_protocol_longer_than_repeat_limit_remains_compatible():
    calls = [
        CommandCall("move", {"instrument": "pipette", "position": f"plate.A{index}"})
        for index in range(1, MAX_EXPANDED_PROTOCOL_STEPS + 2)
    ]

    protocol = compile_protocol(calls)

    assert len(protocol.steps) == MAX_EXPANDED_PROTOCOL_STEPS + 1
    assert protocol.steps[0].args["position"] == "plate.A1"
    assert protocol.steps[-1].index == MAX_EXPANDED_PROTOCOL_STEPS
    assert protocol.steps[-1].args["position"] == f"plate.A{MAX_EXPANDED_PROTOCOL_STEPS + 1}"
