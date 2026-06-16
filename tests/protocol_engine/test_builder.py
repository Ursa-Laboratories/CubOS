"""Tests for the Python protocol builder and shared compilation."""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from protocol_engine.builder import ProtocolBuilder, wells
from protocol_engine.compiler import CommandCall, compile_protocol
from protocol_engine.protocol import ProtocolSetup
from protocol_engine.registry import CommandRegistry


@pytest.fixture(autouse=True)
def _ensure_commands_registered():
    required_commands = {"home", "measure", "move", "pause", "scan"}
    if required_commands.issubset(set(CommandRegistry.instance().command_names)):
        return

    modules = [
        importlib.import_module("protocol_engine.commands.home"),
        importlib.import_module("protocol_engine.commands.measure"),
        importlib.import_module("protocol_engine.commands.move"),
        importlib.import_module("protocol_engine.commands.pause"),
        importlib.import_module("protocol_engine.commands.scan"),
    ]
    CommandRegistry.reset()
    for module in modules:
        importlib.reload(module)


def _step_signature(protocol):
    return [
        (step.index, step.command_name, step.args)
        for step in protocol.steps
    ]


def test_compile_protocol_uses_registry_validation_and_omits_defaults():
    protocol = compile_protocol([
        CommandCall(
            command="pause",
            args={"seconds": 0.5},
        ),
    ])

    assert _step_signature(protocol) == [(0, "pause", {"seconds": 0.5})]


def test_compile_protocol_rejects_unknown_command_through_registry():
    with pytest.raises(KeyError, match="Unknown protocol command"):
        compile_protocol([CommandCall(command="unknown_cmd", args={})])


def test_compile_protocol_rejects_invalid_args_through_pydantic():
    with pytest.raises(ValidationError, match="instrument"):
        compile_protocol([
            CommandCall(command="move", args={"position": "plate_1.A1"}),
        ])


def test_wells_returns_row_major_targets():
    assert wells("plate", rows="A:D", columns=range(1, 7)) == [
        "plate.A1",
        "plate.A2",
        "plate.A3",
        "plate.A4",
        "plate.A5",
        "plate.A6",
        "plate.B1",
        "plate.B2",
        "plate.B3",
        "plate.B4",
        "plate.B5",
        "plate.B6",
        "plate.C1",
        "plate.C2",
        "plate.C3",
        "plate.C4",
        "plate.C5",
        "plate.C6",
        "plate.D1",
        "plate.D2",
        "plate.D3",
        "plate.D4",
        "plate.D5",
        "plate.D6",
    ]


def test_builder_supports_registered_commands_without_typed_wrapper():
    protocol = (
        ProtocolBuilder()
        .add_command("breakpoint", message="Continue?")
        .build()
    )

    assert _step_signature(protocol) == [
        (0, "breakpoint", {"message": "Continue?"}),
    ]


def test_builder_omits_defaults_unless_explicitly_set():
    implicit_default = ProtocolBuilder().add_pause(1.0).build()
    explicit_default = ProtocolBuilder().add_pause(1.0, reason="").build()

    assert implicit_default.steps[0].args == {"seconds": 1.0}
    assert explicit_default.steps[0].args == {"seconds": 1.0, "reason": ""}


def test_builder_mutation_after_build_does_not_mutate_built_protocol():
    protocol_builder = ProtocolBuilder()
    protocol_builder.add_position("park", [1.0, 2.0, 3.0])
    protocol_builder.add_move(
        instrument="pipette",
        position="park",
        travel_z=10.0,
    )

    protocol = protocol_builder.build()

    protocol_builder.add_position("park", [9.0, 9.0, 9.0])
    protocol_builder.add_home()

    assert protocol.positions == {"park": [1.0, 2.0, 3.0]}
    assert _step_signature(protocol) == [
        (
            0,
            "move",
            {
                "instrument": "pipette",
                "position": "park",
                "travel_z": 10.0,
            },
        ),
    ]


def test_with_setup_attaches_setup_metadata():
    protocol = (
        ProtocolBuilder.with_setup(
            gantry_path="configs/gantry/cub_xl_asmi.yaml",
            deck_path="configs/deck/asmi_deck.yaml",
        )
        .add_home()
        .build()
    )

    assert protocol.setup == ProtocolSetup(
        gantry_path="configs/gantry/cub_xl_asmi.yaml",
        deck_path="configs/deck/asmi_deck.yaml",
    )


def test_builder_without_setup_has_no_setup_metadata():
    protocol = ProtocolBuilder().add_home().build()
    assert protocol.setup is None
