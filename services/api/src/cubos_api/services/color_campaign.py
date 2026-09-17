"""Generate the fixed-volume three-stock color-matching campaign."""

from __future__ import annotations

import copy
import math
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


def _source_steps(source_protocol_yaml: str, *, batch_size: int) -> list[dict]:
    try:
        document = yaml.safe_load(source_protocol_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(f"Cannot parse source color protocol: {exc}") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"protocol"}
        or not isinstance(document.get("protocol"), list)
    ):
        raise ValueError(
            "Source color protocol must contain only a protocol list; other "
            "sections cannot be silently omitted"
        )
    steps = document["protocol"]
    expected = [
        "pick_up_tip", "transfer", "drop_tip",
        "pick_up_tip", "transfer", "drop_tip",
        "pick_up_tip", "transfer", "mix", "drop_tip",
    ]
    observed = [
        next(iter(step)) if isinstance(step, dict) and len(step) == 1 else None
        for step in steps
    ]
    if observed != expected:
        raise ValueError(
            "Source color protocol must be exactly three pickup/transfer groups "
            "with a final mix and drop; unsupported steps cannot be silently omitted"
        )
    for index, step in enumerate(steps):
        args = next(iter(step.values()))
        if not isinstance(args, dict):
            raise ValueError(f"Source color protocol step {index} needs arguments")
    for index in (1, 4, 7):
        transfer = steps[index]["transfer"]
        if not all(key in transfer for key in ("source", "destination", "volume_ul")):
            raise ValueError(f"Source color transfer step {index} is incomplete")
        destination_height = transfer.get("destination_height", 0.0)
        try:
            destination_height = float(destination_height)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Source color transfer step {index} has invalid destination_height"
            ) from exc
        if not math.isfinite(destination_height):
            raise ValueError("Destination height must be finite")
        if batch_size > 1 and destination_height < 0:
            raise ValueError(
                "Shared dye tips require a nonnegative destination_height to "
                "dispense above or at the calibrated well reference"
            )
    mix = steps[8]["mix"]
    if not all(key in mix for key in ("position", "volume_ul", "cycles", "height")):
        raise ValueError("Source color mix step is incomplete")
    return copy.deepcopy(steps)


def target_protocol(
    target_well: str,
    camera: str,
    roi_fraction: float,
    image_height: float | None = None,
    expected_center: tuple[float, float] | None = None,
    expected_center_source: str | None = None,
) -> str:
    measure_args: dict[str, object] = {
        "instrument": camera,
        "position": target_well,
        "label": "color_target",
        "roi_fraction": roi_fraction,
    }
    if image_height is not None:
        measure_args["image_height"] = image_height
    if expected_center is not None:
        measure_args["expected_center"] = list(expected_center)
        measure_args["expected_center_source"] = expected_center_source
    return yaml.safe_dump({"protocol": [
        {"move": {"instrument": camera, "position": target_well}},
        {"measure_color": measure_args},
    ]}, sort_keys=False)


def build_color_campaign(
    setup: ColorCampaignSetup,
    protocol_directory: Path,
    *,
    available_tip_positions: list[str] | None = None,
    source_protocol_yaml: str,
) -> CampaignSpec:
    """Write an immutable generated protocol and return its campaign spec."""
    if setup.target_lab is None or setup.reference_processing_profile_id is None:
        raise ValueError("Color campaign requires an accepted target measurement and profile")
    source_steps = _source_steps(source_protocol_yaml, batch_size=setup.batch_size)
    trial_count = len(setup.candidate_wells)
    batch_size = setup.batch_size
    required_tips = (
        trial_count * 3 if batch_size == 1
        else sum(3 + min(batch_size, trial_count - start)
                 for start in range(0, trial_count, batch_size))
    )
    if available_tip_positions is None:
        available_tip_positions = [
            f"tips.{chr(ord('A') + index // 12)}{index % 12 + 1}"
            for index in range(required_tips)
        ]
    if len(available_tip_positions) < required_tips:
        raise ValueError(
            f"Color campaign needs {required_tips} available tips for "
            f"{trial_count} trials, but the durable state has "
            f"{len(available_tip_positions)}."
        )
    tip_values: dict[str, list[str]] = {
        "red_tip": [], "yellow_tip": [], "blue_tip": [], "mix_tip": [],
    }
    cursor = 0
    for start in range(0, trial_count, batch_size):
        count = min(batch_size, trial_count - start)
        if batch_size == 1:
            red, yellow, blue = available_tip_positions[cursor:cursor + 3]
            cursor += 3
            mixes: list[str] = []
        else:
            red, yellow, blue = available_tip_positions[cursor:cursor + 3]
            mixes = available_tip_positions[cursor + 3:cursor + 3 + count]
            cursor += 3 + count
        tip_values["red_tip"].extend([red] * count)
        tip_values["yellow_tip"].extend([yellow] * count)
        tip_values["blue_tip"].extend([blue] * count)
        tip_values["mix_tip"].extend(mixes)

    first_well = setup.candidate_wells[0]
    steps: list[dict] = []
    for color, pickup_index, transfer_index, drop_index, volume in (
        ("red", 0, 1, 2, INITIAL_POINTS[0]["red_ul"]),
        ("yellow", 3, 4, 5, INITIAL_POINTS[0]["yellow_ul"]),
        ("blue", 6, 7, 9, INITIAL_POINTS[0]["blue_ul"]),
    ):
        pickup = copy.deepcopy(source_steps[pickup_index])
        pickup["pick_up_tip"]["position"] = tip_values[f"{color}_tip"][0]
        transfer = copy.deepcopy(source_steps[transfer_index])
        transfer["transfer"].update({
            "source": getattr(setup, f"{color}_source"),
            "destination": first_well,
            "volume_ul": volume,
        })
        steps.extend((pickup, transfer))
        if color != "blue" or batch_size > 1:
            steps.append(copy.deepcopy(source_steps[drop_index]))
    if batch_size > 1:
        mix_pickup = copy.deepcopy(source_steps[6])
        mix_pickup["pick_up_tip"]["position"] = tip_values["mix_tip"][0]
        steps.append(mix_pickup)
    mix_step = copy.deepcopy(source_steps[8])
    mix_step["mix"]["position"] = first_well
    steps.extend((mix_step, copy.deepcopy(source_steps[9])))
    steps.extend((
        {"move": {"instrument": setup.camera_instrument, "position": first_well}},
        {"measure_color": {
            "instrument": setup.camera_instrument,
            "position": first_well,
            "label": "color_candidate",
            "roi_fraction": setup.roi_fraction,
            "reference_lab": list(setup.target_lab),
            "reference_processing_profile_id": setup.reference_processing_profile_id,
            "expected_center": list(setup.expected_center),
            "expected_center_source": setup.expected_center_source,
            **(
                {"image_height": setup.image_height}
                if setup.image_height is not None else {}
            ),
        }},
    ))
    protocol = {"protocol": steps}
    filename = f"ade_color_matching_{uuid.uuid4().hex[:8]}.yaml"
    transfer_indexes = (1, 4, 7)
    mix_index = 10 if batch_size > 1 else 8
    move_index = mix_index + 2
    measure_index = move_index + 1
    destination_bindings = [
        {"step_index": index, "argument": argument}
        for index, argument in (
            *((index, "destination") for index in transfer_indexes),
            (mix_index, "position"),
            (move_index, "position"),
            (measure_index, "position"),
        )
    ]
    spec = CampaignSpec(
        name="CIEDE2000 color matching",
        gantry_file=setup.gantry_file,
        deck_file=setup.deck_file,
        protocol_file=filename,
        parameters=[
            {"name": "red_ul", "minimum": 50.0, "maximum": 200.0, "step": 5.0,
             "bindings": [{"step_index": transfer_indexes[0], "argument": "volume_ul"}]},
            {"name": "yellow_ul", "minimum": 50.0, "maximum": 200.0, "step": 5.0,
             "bindings": [{"step_index": transfer_indexes[1], "argument": "volume_ul"}]},
            {"name": "blue_ul", "minimum": 50.0, "maximum": 200.0, "step": 5.0,
             "bindings": [{"step_index": transfer_indexes[2], "argument": "volume_ul"}]},
        ],
        sequences=[
            {"name": "candidate_well", "values": setup.candidate_wells,
             "bindings": destination_bindings},
            *[
                {"name": f"{color}_tip", "values": tip_values[f"{color}_tip"],
                 "bindings": [{"step_index": step, "argument": "position"}]}
                for color, step in (("red", 0), ("yellow", 3), ("blue", 6))
            ],
            *([{"name": "mix_tip", "values": tip_values["mix_tip"],
                "bindings": [{"step_index": 9, "argument": "position"}]}]
              if batch_size > 1 else []),
        ],
        objective={"mode": "result", "path": f"{measure_index}.delta_e_00", "direction": "minimize"},
        optimizer={"method": "ei", "kernel": "matern52", "initial_trials": 6,
                   "initial_points": INITIAL_POINTS, "exploration": 0.05, "seed": 7},
        stop={"max_trials": trial_count, "target_value": 3.0, "patience": 0,
              "min_improvement": 0.0, "max_seconds": None},
        sum_constraint={"parameters": ["red_ul", "yellow_ul", "blue_ul"], "total": 300.0},
        mock_mode=setup.mock_mode,
        fluid_state_id=setup.fluid_state_id,
        batch_size=batch_size,
        source_protocol_file=setup.source_protocol_file,
    )
    protocol_directory.mkdir(parents=True, exist_ok=True)
    (protocol_directory / filename).write_text(yaml.safe_dump(protocol, sort_keys=False))
    return spec
