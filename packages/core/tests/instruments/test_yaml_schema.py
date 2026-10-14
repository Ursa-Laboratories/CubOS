import pytest
from pydantic import ValidationError

from cubos.instruments.yaml_schema import InstrumentYamlEntry


@pytest.mark.parametrize("field", ["offset_x", "offset_y", "depth"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_mount_geometry_is_rejected(field, value):
    with pytest.raises(ValidationError) as exc_info:
        InstrumentYamlEntry(type="camera", vendor="mount_only", **{field: value})
    assert exc_info.value.errors()[0]["loc"] == (field,)


def test_signed_mount_geometry_and_vendor_fields_are_preserved():
    entry = InstrumentYamlEntry(
        type="camera",
        vendor="mount_only",
        offset_x=-10.5,
        offset_y=20.0,
        depth=-5.0,
        serial_number="nan",
    )
    assert entry.model_dump() == {
        "type": "camera",
        "vendor": "mount_only",
        "offset_x": -10.5,
        "offset_y": 20.0,
        "depth": -5.0,
        "serial_number": "nan",
    }
