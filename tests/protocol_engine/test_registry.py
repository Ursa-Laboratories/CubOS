"""Tests for the @protocol_command decorator and CommandRegistry."""

import importlib
import inspect
from typing import get_args, get_origin

import pytest
from pydantic import ValidationError

from protocol_engine.registry import (
    CommandRegistry,
    _build_schema_from_signature,
    protocol_command,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Reset the singleton before and after each test."""
    CommandRegistry.reset()
    yield
    CommandRegistry.reset()


# ─── Registration ────────────────────────────────────────────────────────────


def test_protocol_command_registers_function():
    @protocol_command("greet")
    def greet(context, name: str) -> None:
        pass

    reg = CommandRegistry.instance()
    assert "greet" in reg.command_names
    assert reg.get("greet").handler is greet


def test_protocol_command_uses_function_name_by_default():
    @protocol_command()
    def hello(context, msg: str) -> None:
        pass

    assert "hello" in CommandRegistry.instance().command_names


def test_protocol_command_uses_explicit_name():
    @protocol_command("custom_name")
    def my_func(context, x: int) -> None:
        pass

    reg = CommandRegistry.instance()
    assert "custom_name" in reg.command_names
    assert reg.get("custom_name").handler is my_func


def test_duplicate_command_name_raises():
    @protocol_command("dup")
    def first(context) -> None:
        pass

    with pytest.raises(ValueError, match="already registered"):

        @protocol_command("dup")
        def second(context) -> None:
            pass


def test_get_unknown_command_raises():
    reg = CommandRegistry.instance()
    with pytest.raises(KeyError, match="Unknown protocol command 'nope'"):
        reg.get("nope")


def test_get_unknown_command_lists_available():
    @protocol_command("alpha")
    def alpha(context) -> None:
        pass

    @protocol_command("beta")
    def beta(context) -> None:
        pass

    reg = CommandRegistry.instance()
    with pytest.raises(KeyError, match="alpha.*beta"):
        reg.get("nope")


def test_reset_clears_registry():
    @protocol_command("tmp")
    def tmp(context) -> None:
        pass

    assert "tmp" in CommandRegistry.instance().command_names
    CommandRegistry.reset()
    assert CommandRegistry.instance().command_names == []


def test_decorator_attaches_metadata():
    @protocol_command("meta")
    def meta(context, x: str) -> None:
        pass

    assert meta._protocol_command_name == "meta"
    assert meta._protocol_schema is not None


# ─── Schema generation ───────────────────────────────────────────────────────


def test_schema_generated_with_correct_fields():
    def sample(context, instrument: str, position: str) -> None:
        pass

    schema = _build_schema_from_signature("sample", sample)
    fields = set(schema.model_fields.keys())
    assert fields == {"instrument", "position"}


def test_schema_skips_context_and_self():
    def method(self, context, value: int) -> None:
        pass

    schema = _build_schema_from_signature("method", method)
    assert set(schema.model_fields.keys()) == {"value"}


def test_schema_forbids_extra_fields():
    def cmd(context, a: str) -> None:
        pass

    schema = _build_schema_from_signature("cmd", cmd)
    with pytest.raises(ValidationError, match="Extra inputs"):
        schema.model_validate({"a": "ok", "b": "extra"})


def test_schema_requires_all_parameters():
    def cmd(context, a: str, b: int) -> None:
        pass

    schema = _build_schema_from_signature("cmd", cmd)
    with pytest.raises(ValidationError):
        schema.model_validate({"a": "only_a"})


def test_schema_respects_default_values():
    def cmd(context, a: str, b: float = 50.0) -> None:
        pass

    schema = _build_schema_from_signature("cmd", cmd)
    result = schema.model_validate({"a": "hello"})
    assert result.a == "hello"
    assert result.b == 50.0


def test_schema_validates_successfully_with_all_fields():
    def cmd(context, instrument: str, position: str) -> None:
        pass

    schema = _build_schema_from_signature("cmd", cmd)
    result = schema.model_validate({"instrument": "pipette", "position": "plate_1.A1"})
    assert result.instrument == "pipette"
    assert result.position == "plate_1.A1"


def test_schema_resolves_postponed_typing_annotations():
    from protocol_engine.commands.pipette import serial_transfer

    schema = _build_schema_from_signature("serial_transfer", serial_transfer)
    result = schema.model_validate({
        "source": "vial_1",
        "plate": "plate_1",
        "axis": "A",
        "volumes": [1.0, 2.0],
    })

    assert result.volumes == [1.0, 2.0]


def _reload_real_command_registry() -> CommandRegistry:
    modules = [
        "protocol_engine.commands.home",
        "protocol_engine.commands.measure",
        "protocol_engine.commands.move",
        "protocol_engine.commands.pause",
        "protocol_engine.commands.pipette",
        "protocol_engine.commands.scan",
    ]
    CommandRegistry.reset()
    for module_name in modules:
        importlib.reload(importlib.import_module(module_name))
    return CommandRegistry.instance()


def _sample_value(annotation):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list:
        return [_sample_value(args[0] if args else str)]
    if origin is dict:
        return {}
    if origin is not None and type(None) in args:
        non_none = next(arg for arg in args if arg is not type(None))
        return _sample_value(non_none)
    if annotation is str:
        return "plate_1.A1"
    if annotation is float:
        return 1.0
    if annotation is int:
        return 1
    return "value"


def test_every_registered_command_schema_validates_required_fields():
    registry = _reload_real_command_registry()

    for command_name in registry.command_names:
        registered = registry.get(command_name)
        signature = inspect.signature(registered.handler)
        args = {}
        for name, parameter in signature.parameters.items():
            if name in {"self", "context"}:
                continue
            if parameter.default is inspect.Parameter.empty:
                field = registered.schema.model_fields[name]
                args[name] = _sample_value(field.annotation)

        registered.schema.model_validate(args)
