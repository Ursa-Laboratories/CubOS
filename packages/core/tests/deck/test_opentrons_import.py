from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from cubos.deck.labware.definitions.opentrons_import import (
    OpentronsImportError,
    convert_opentrons_labware,
    import_opentrons_labware,
)
from cubos.deck.loader import load_deck_from_yaml
from cubos.tools.import_opentrons_labware import main

FIXTURES = Path(__file__).parent / "fixtures" / "opentrons"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_plate_converts_to_a_well_plate_config():
    imported = import_opentrons_labware(FIXTURES / "plate_2x3.json")
    config = imported.config
    assert (config["rows"], config["columns"]) == (2, 3)
    assert config["well_depth"] == 10.0
    assert (config["well_shape"], config["well_diameter"]) == ("circular", 6.4)
    assert config["x_offset"] == 9.0 and config["y_offset"] == 9.0
    assert config["calibration"]["a1"] == {"x": 14.38, "y": 24.24}
    assert config["calibration"]["a2"] == {"x": 23.38, "y": 24.24}
    assert (config["length"], config["width"], config["height"]) == (40.0, 30.0, 14.0)
    assert config["capacity_ul"] == config["working_volume_ul"] == 200.0
    assert config["well_attributes"] == {
        "source": "opentrons:fixture/fixture_6_wellplate_200ul/v1", "bottom": "flat",
    }
    assert any("working_volume_ul" in w for w in imported.warnings)


def test_converted_definition_loads_into_a_deck_with_opentrons_well_layout(tmp_path):
    imported = import_opentrons_labware(FIXTURES / "plate_2x3.json")
    config = imported.config
    config["calibration"]["a1"]["z"] = 20.0
    deck_path = tmp_path / "deck.yaml"
    deck_path.write_text(yaml.safe_dump({"labware": {"plate": config}}), encoding="utf-8")
    plate = load_deck_from_yaml(deck_path)["plate"]
    source = _load("plate_2x3.json")["wells"]
    for well_id, point in plate.wells.items():
        assert point.x == pytest.approx(source[well_id]["x"], abs=1e-3)
        assert point.y == pytest.approx(source[well_id]["y"], abs=1e-3)
    assert plate.well_depth == 10.0 and plate.well_shape == "circular"


def test_trough_converts_with_rectangular_cross_section_and_warns_on_single_row():
    imported = import_opentrons_labware(FIXTURES / "trough_1x4.json")
    config = imported.config
    assert (config["rows"], config["columns"]) == (1, 4)
    assert (config["well_x_dimension"], config["well_y_dimension"]) == (8.0, 70.0)
    assert config["x_offset"] == 18.0
    assert config["y_offset"] == 9.0
    assert any("single row" in w for w in imported.warnings)
    assert "bottom" not in config["well_attributes"]


def test_single_well_labware_gets_both_placeholder_pitches():
    data = _load("trough_1x4.json")
    data["ordering"] = [["A1"]]
    data["wells"] = {"A1": data["wells"]["A1"]}
    config = convert_opentrons_labware(data).config
    assert (config["rows"], config["columns"]) == (1, 1)
    assert config["x_offset"] == config["y_offset"] == 9.0


def _mutated(name, mutate):
    data = copy.deepcopy(_load(name))
    mutate(data)
    return data


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(schemaVersion=1), "schemaVersion"),
        (lambda d: d["parameters"].update(isTiprack=True), "tip racks"),
        (lambda d: d.pop("wells"), "no wells"),
        (lambda d: d["parameters"].pop("loadName"), "loadName"),
        (lambda d: d["wells"]["B2"].update(x=99.0), "not aligned"),
        (lambda d: [d["wells"][w].update(x=40.0) for w in ("A3", "B3")], "spacing is not uniform"),
        (lambda d: d["wells"]["B2"].update(depth=5.0), "well depth is not uniform"),
        (lambda d: d["wells"]["B2"].update(totalLiquidVolume=300), "totalLiquidVolume"),
        (lambda d: d["wells"]["B2"].update(shape="rectangular", xDimension=6, yDimension=6), "one circular or rectangular"),
        (lambda d: d["wells"]["B2"].update(diameter=8.0), "diameter is not uniform"),
        (lambda d: d["ordering"][2].pop(), "different lengths"),
        (lambda d: d["ordering"].__setitem__(0, ["A1", "C1"]), "different well ids"),
        (lambda d: d["dimensions"].update(zDimension=5.0), "invalid"),
        (lambda d: d["wells"]["A1"].update(depth="deep"), "finite number"),
    ],
)
def test_unconvertible_definitions_are_rejected(mutate, match):
    with pytest.raises(OpentronsImportError, match=match):
        convert_opentrons_labware(_mutated("plate_2x3.json", mutate))


def test_reversed_row_or_column_order_is_rejected():
    data = _mutated("plate_2x3.json", lambda d: [w.update(x=100.0 - w["x"]) for w in d["wells"].values()])
    with pytest.raises(OpentronsImportError, match="must run"):
        convert_opentrons_labware(data)


def test_non_lettered_layout_is_rejected():
    data = _mutated("plate_2x3.json", lambda d: d["ordering"].reverse())
    with pytest.raises(OpentronsImportError, match="not at row"):
        convert_opentrons_labware(data)


def test_unreadable_files_report_cleanly(tmp_path):
    with pytest.raises(OpentronsImportError, match="cannot read"):
        import_opentrons_labware(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(OpentronsImportError, match="JSON object"):
        import_opentrons_labware(bad)


def test_rim_height_mismatch_warns():
    data = _mutated("plate_2x3.json", lambda d: d["wells"]["B2"].update(z=9.0))
    assert any("rim heights differ" in w for w in convert_opentrons_labware(data).warnings)


def test_cli_writes_yaml_and_reports_errors(tmp_path, capsys):
    out = tmp_path / "plate.yaml"
    assert main([str(FIXTURES / "plate_2x3.json"), "-o", str(out)]) == 0
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["well_depth"] == 10.0
    assert "WARNING" in capsys.readouterr().err
    assert main([str(FIXTURES / "plate_2x3.json")]) == 0
    assert "well_depth" in capsys.readouterr().out
    assert main([str(FIXTURES / "tiprack.json")]) == 1
    assert "ERROR" in capsys.readouterr().err
