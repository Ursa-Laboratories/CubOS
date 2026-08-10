"""Coverage tests for every entry in the labware definitions registry.

Each definition's config YAML is deck-YAML-entry shaped (it carries a
``type:`` key that the deck loader dispatches on), so the meaningful
validation is against the matching ``*YamlEntry`` schema rather than the
labware constructor directly.

Without this sweep a definition with a stray key, a bad ``type:``, or an
unimportable ``module:`` stays green until some deck YAML happens to
reference it — which means the failure surfaces at hardware bring-up
rather than in CI.
"""

from __future__ import annotations

from typing import Any

import pytest

from cubos.deck import LABWARE_YAML_ENTRY_MODELS
from cubos.deck.labware.definitions.registry import (
    get_labware_class,
    get_supported_definitions,
    load_definition_config,
)
from cubos.deck.labware.labware import Labware


# Minimal per-instance fields a deck YAML must supply for each entry type.
# Definitions deliberately omit these (measured coordinates, pickup heights),
# so the sweep injects placeholders rather than treating their absence as a
# definition defect.
_MINIMAL_INSTANCE_FIELDS: dict[str, dict[str, Any]] = {
    "well_plate": {
        "calibration": {
            "a1": {"x": 0.0, "y": 0.0, "z": -10.0},
            "a2": {"x": 9.0, "y": 0.0, "z": -10.0},
        },
    },
    "vial_grid": {
        "calibration": {
            "a1": {"x": 0.0, "y": 0.0, "z": -10.0},
            "a2": {"x": 9.0, "y": 0.0, "z": -10.0},
        },
    },
    "tip_rack": {
        "calibration": {
            "a1": {"x": 0.0, "y": 0.0, "z": -10.0},
            "a2": {"x": 9.0, "y": 0.0, "z": -10.0},
        },
        "pickup_z": -10.0,
    },
    "vial": {"location": {"x": 0.0, "y": 0.0, "z": -10.0}},
    "well_plate_holder": {"location": {"x": 0.0, "y": 0.0, "z": -10.0}},
    "vial_holder": {"location": {"x": 0.0, "y": 0.0, "z": -10.0}},
    "tip_disposal": {"location": {"x": 0.0, "y": 0.0, "z": -10.0}},
    "wall": {
        "corner_1": {"x": 0.0, "y": 0.0, "z": 0.0},
        "corner_2": {"x": 10.0, "y": 10.0, "z": 10.0},
    },
}


def test_registry_is_not_empty():
    """Guards against the parametrized sweeps below silently covering nothing."""
    assert get_supported_definitions()


@pytest.mark.parametrize("definition", get_supported_definitions())
def test_definition_class_and_module_resolve(definition: str):
    """`module:` imports and `class_name:` names a real Labware subclass."""
    cls = get_labware_class(definition)

    assert isinstance(cls, type)
    assert issubclass(cls, Labware), f"{definition} does not resolve to a Labware subclass"


@pytest.mark.parametrize("definition", get_supported_definitions())
def test_definition_config_declares_a_known_type(definition: str):
    config = load_definition_config(definition)

    assert "type" in config, f"{definition} config is missing a `type:` key"
    assert config["type"] in LABWARE_YAML_ENTRY_MODELS, (
        f"{definition} declares unknown type {config['type']!r}; "
        f"known types: {sorted(LABWARE_YAML_ENTRY_MODELS)}"
    )


@pytest.mark.parametrize("definition", get_supported_definitions())
def test_definition_config_validates_against_its_entry_schema(definition: str):
    """Every key in the config is accepted by the schema.

    The entry models set ``extra="forbid"``, so this is what catches a stray
    or misspelled key in a definition YAML.
    """
    config = load_definition_config(definition)
    entry_type = config["type"]
    model = LABWARE_YAML_ENTRY_MODELS[entry_type]

    # Definition config wins over the placeholders, so a definition that does
    # supply its own calibration/location is validated as written.
    payload = {**_MINIMAL_INSTANCE_FIELDS.get(entry_type, {}), **config}

    model.model_validate(payload)


@pytest.mark.parametrize("definition", get_supported_definitions())
def test_definition_config_type_matches_registered_class(definition: str):
    """The config's `type:` and the registry's `class_name:` agree."""
    config = load_definition_config(definition)
    entry_model = LABWARE_YAML_ENTRY_MODELS[config["type"]]
    cls = get_labware_class(definition)

    # The entry model name mirrors the labware class name for every current
    # type (WellPlate/WellPlateYamlEntry, TipRack/TipRackYamlEntry, ...).
    assert entry_model.__name__ == f"{cls.__name__}YamlEntry", (
        f"{definition}: config type {config['type']!r} maps to "
        f"{entry_model.__name__}, but the registry class is {cls.__name__}"
    )
