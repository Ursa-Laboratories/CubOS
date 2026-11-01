import pytest
from pydantic import ValidationError

from cubos.protocol_engine.commands import pipette
from cubos.protocol_engine.errors import ProtocolExecutionError
from cubos.protocol_engine.pipette_routing import validate_pipette_travel_clearance


@pytest.mark.parametrize("command", ["aspirate", "dispense", "blowout", "mix", "transfer"])
def test_registered_commands_expose_clearance_metadata(command):
    schema = getattr(pipette, command)._protocol_schema
    field = schema.model_fields["travel_clearance"]
    assert field.default == 3.0
    schema_property = schema.model_json_schema()["properties"]["travel_clearance"]
    assert "registered plate top" in schema_property["description"]
    assert field.annotation is not None


@pytest.mark.parametrize("command", ["aspirate", "dispense", "blowout", "mix", "transfer"])
@pytest.mark.parametrize("value", ["3", True, -0.1, float("nan"), float("inf")])
def test_registered_schema_rejects_invalid_clearance(command, value):
    schema = getattr(pipette, command)._protocol_schema
    data = {}
    for name, field in schema.model_fields.items():
        if name == "travel_clearance":
            continue
        if field.is_required():
            data[name] = "plate.A1" if name in {"position", "source", "destination"} else 1
    data["travel_clearance"] = value
    with pytest.raises(ValidationError):
        schema.model_validate(data)


@pytest.mark.parametrize(
    ("command", "args"),
    [
        (pipette.aspirate, ("plate.A1", 1.0)),
        (pipette.dispense, ("plate.A1", 1.0)),
        (pipette.blowout, ("plate.A1",)),
        (pipette.mix, ("plate.A1", 1.0)),
        (pipette.transfer, ("plate.A1", "plate.A2", 1.0)),
    ],
)
@pytest.mark.parametrize("value", ["3", True, -0.1, float("nan"), float("inf")])
def test_direct_handler_validates_before_context_actions(command, args, value):
    with pytest.raises(ProtocolExecutionError, match="travel_clearance"):
        command(object(), *args, travel_clearance=value)


def test_clearance_accepts_null_and_nonnegative_finite_values():
    assert validate_pipette_travel_clearance(None) is None
    assert validate_pipette_travel_clearance(0) == 0.0
    assert validate_pipette_travel_clearance(2.5) == 2.5
