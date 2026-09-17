import json
from pathlib import Path

import yaml

from cubos_api.models.campaigns import ColorCampaignSetup
from cubos_api.services.campaign_templates import extract_result_objective
from cubos_api.services.color_campaign import build_color_campaign, target_protocol


SOURCE_PROTOCOL = """protocol:
- pick_up_tip: {position: tips.A1}
- transfer: {source: stocks.A1, destination: plate.A1, volume_ul: 100, source_height: '-20'}
- drop_tip: {position: waste}
- pick_up_tip: {position: tips.A2}
- transfer: {source: stocks.A2, destination: plate.A1, volume_ul: 100, source_height: '-20'}
- drop_tip: {position: waste}
- pick_up_tip: {position: tips.A3}
- transfer: {source: stocks.A3, destination: plate.A1, volume_ul: 100, source_height: '-20'}
- mix: {position: plate.A1, volume_ul: 60, cycles: 3, height: -7}
- drop_tip: {position: waste}
"""


def setup() -> ColorCampaignSetup:
    return ColorCampaignSetup(
        gantry_file="g.yaml",
        deck_file="d.yaml",
        source_protocol_file="source.yaml",
        target_well="plate.A1",
        target_lab=(42.0, 12.0, 18.0),
        reference_processing_profile_id="profile-v1",
        red_source="stocks.A1",
        yellow_source="stocks.A2",
        blue_source="stocks.A3",
        candidate_wells=[f"plate.A{index}" for index in range(2, 8)],
        camera_instrument="camera",
        roi_fraction=0.5,
        expected_center=(0.5, 0.5),
        expected_center_source="operator_selected",
        mock_mode=True,
    )


def test_target_protocol_reads_selected_well_without_fluid_steps():
    document = yaml.safe_load(target_protocol("plate.C4", "camera", 0.45))
    assert document["protocol"] == [
        {"move": {"instrument": "camera", "position": "plate.C4"}},
        {"measure_color": {
            "instrument": "camera",
            "position": "plate.C4",
            "label": "color_target",
            "roi_fraction": 0.45,
        }},
    ]


def test_builder_writes_complete_protocol_and_campaign(tmp_path: Path):
    spec = build_color_campaign(setup(), tmp_path, source_protocol_yaml=SOURCE_PROTOCOL)
    protocol = yaml.safe_load((tmp_path / spec.protocol_file).read_text())["protocol"]
    assert protocol[1]["transfer"]["source"] == "stocks.A1"
    assert protocol[4]["transfer"]["source"] == "stocks.A2"
    assert protocol[7]["transfer"]["source"] == "stocks.A3"
    assert protocol[11]["measure_color"]["reference_lab"] == [42.0, 12.0, 18.0]
    assert protocol[11]["measure_color"]["reference_processing_profile_id"] == "profile-v1"
    assert protocol[11]["measure_color"]["expected_center"] == [0.5, 0.5]
    assert spec.objective.path == "11.delta_e_00"
    result = [None] * 11 + [{"delta_e_00": 2.4}]
    assert extract_result_objective(result, spec.objective.path) == 2.4
    assert spec.sum_constraint.total == 300
    assert spec.optimizer.initial_points[0] == {
        "red_ul": 200.0, "yellow_ul": 50.0, "blue_ul": 50.0,
    }
    assert spec.sequences[0].values == [f"plate.A{index}" for index in range(2, 8)]
    assert spec.sequences[1].values[:2] == ["tips.A1", "tips.A4"]


def test_builder_allocates_each_trial_from_durable_available_tip_order(tmp_path: Path):
    available = [
        f"tips.{chr(ord('A') + index // 12)}{index % 12 + 1}"
        for index in range(3, 21)
    ]
    spec = build_color_campaign(
        setup(), tmp_path, available_tip_positions=available,
        source_protocol_yaml=SOURCE_PROTOCOL,
    )

    assert spec.sequences[1].values[:2] == ["tips.A4", "tips.A7"]
    assert spec.sequences[2].values[:2] == ["tips.A5", "tips.A8"]
    assert spec.sequences[3].values[:2] == ["tips.A6", "tips.A9"]


def test_builder_rejects_insufficient_durable_tip_capacity(tmp_path: Path):
    import pytest

    with pytest.raises(ValueError, match="needs 18 available tips"):
        build_color_campaign(
            setup(), tmp_path,
            available_tip_positions=[
                f"tips.{chr(ord('A') + index // 12)}{index % 12 + 1}"
                for index in range(3, 19)
            ],
            source_protocol_yaml=SOURCE_PROTOCOL,
        )


def test_target_cannot_be_reused_as_candidate():
    raw = setup().model_dump()
    raw["candidate_wells"] = ["plate.A1", "plate.A2", "plate.A3", "plate.A4", "plate.A5", "plate.A6"]
    import pytest
    with pytest.raises(ValueError, match="Target well"):
        ColorCampaignSetup.model_validate(raw)


def test_setup_accepts_target_lab_from_json_array():
    raw = setup().model_dump(mode="json")
    assert isinstance(raw["target_lab"], list)
    parsed = ColorCampaignSetup.model_validate_json(json.dumps(raw))
    assert parsed.target_lab == (42.0, 12.0, 18.0)
