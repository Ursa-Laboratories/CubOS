"""Generate the fixed-volume three-stock color-matching campaign."""

from __future__ import annotations

import uuid
from pathlib import Path

import yaml

from cubos_api.models.campaigns import CampaignSpec, ColorCampaignSetup


INITIAL_POINTS = [
    {"red_ul": 200.0, "yellow_ul": 50.0, "blue_ul": 50.0},
    {"red_ul": 50.0, "yellow_ul": 200.0, "blue_ul": 50.0},
    {"red_ul": 50.0, "yellow_ul": 50.0, "blue_ul": 200.0},
    {"red_ul": 125.0, "yellow_ul": 125.0, "blue_ul": 50.0},
    {"red_ul": 125.0, "yellow_ul": 50.0, "blue_ul": 125.0},
    {"red_ul": 50.0, "yellow_ul": 125.0, "blue_ul": 125.0},
]


def _tip_slots(count: int, offset: int) -> list[str]:
    slots = []
    for trial in range(count):
        index = trial * 3 + offset
        row = chr(ord("A") + index // 12)
        slots.append(f"tips.{row}{index % 12 + 1}")
    return slots


def target_protocol(target_well: str, camera: str, roi_fraction: float) -> str:
    return yaml.safe_dump({"protocol": [
        {"move": {"instrument": camera, "position": target_well}},
        {"measure_color": {
            "instrument": camera,
            "position": target_well,
            "label": "color_target",
            "roi_fraction": roi_fraction,
        }},
    ]}, sort_keys=False)


def build_color_campaign(
    setup: ColorCampaignSetup,
    protocol_directory: Path,
) -> CampaignSpec:
    """Write an immutable generated protocol and return its campaign spec."""
    protocol = {"protocol": [
        {"pick_up_tip": {"position": "tips.A1"}},
        {"transfer": {"source": setup.red_source, "destination": setup.candidate_wells[0], "volume_ul": 200.0, "source_height": -8.0}},
        {"drop_tip": {"position": "waste"}},
        {"pick_up_tip": {"position": "tips.A2"}},
        {"transfer": {"source": setup.yellow_source, "destination": setup.candidate_wells[0], "volume_ul": 50.0, "source_height": -8.0}},
        {"drop_tip": {"position": "waste"}},
        {"pick_up_tip": {"position": "tips.A3"}},
        {"transfer": {"source": setup.blue_source, "destination": setup.candidate_wells[0], "volume_ul": 50.0, "source_height": -8.0}},
        {"mix": {"position": setup.candidate_wells[0], "volume_ul": 225.0, "cycles": 3, "height": -3.0}},
        {"drop_tip": {"position": "waste"}},
        {"move": {"instrument": setup.camera_instrument, "position": setup.candidate_wells[0]}},
        {"measure_color": {
            "instrument": setup.camera_instrument,
            "position": setup.candidate_wells[0],
            "label": "color_candidate",
            "roi_fraction": setup.roi_fraction,
            "reference_lab": list(setup.target_lab),
        }},
    ]}
    protocol_directory.mkdir(parents=True, exist_ok=True)
    filename = f"ade_color_matching_{uuid.uuid4().hex[:8]}.yaml"
    (protocol_directory / filename).write_text(yaml.safe_dump(protocol, sort_keys=False))
    trial_count = len(setup.candidate_wells)
    destination_bindings = [
        {"step_index": index, "argument": argument}
        for index, argument in ((1, "destination"), (4, "destination"),
                                (7, "destination"), (8, "position"),
                                (10, "position"), (11, "position"))
    ]
    return CampaignSpec(
        name="CIEDE2000 color matching",
        gantry_file=setup.gantry_file,
        deck_file=setup.deck_file,
        protocol_file=filename,
        parameters=[
            {"name": "red_ul", "minimum": 50.0, "maximum": 200.0, "step": 5.0,
             "bindings": [{"step_index": 1, "argument": "volume_ul"}]},
            {"name": "yellow_ul", "minimum": 50.0, "maximum": 200.0, "step": 5.0,
             "bindings": [{"step_index": 4, "argument": "volume_ul"}]},
            {"name": "blue_ul", "minimum": 50.0, "maximum": 200.0, "step": 5.0,
             "bindings": [{"step_index": 7, "argument": "volume_ul"}]},
        ],
        sequences=[
            {"name": "candidate_well", "values": setup.candidate_wells,
             "bindings": destination_bindings},
            *[
                {"name": f"{color}_tip", "values": _tip_slots(trial_count, offset),
                 "bindings": [{"step_index": step, "argument": "position"}]}
                for color, offset, step in (("red", 0, 0), ("yellow", 1, 3), ("blue", 2, 6))
            ],
        ],
        objective={"mode": "result", "path": "11.delta_e_00", "direction": "minimize"},
        optimizer={"method": "ei", "kernel": "matern52", "initial_trials": 6,
                   "initial_points": INITIAL_POINTS, "exploration": 0.05, "seed": 7},
        stop={"max_trials": trial_count, "target_value": 3.0, "patience": 0,
              "min_improvement": 0.0, "max_seconds": None},
        sum_constraint={"parameters": ["red_ul", "yellow_ul", "blue_ul"], "total": 300.0},
        mock_mode=setup.mock_mode,
        fluid_state_id=setup.fluid_state_id,
    )
