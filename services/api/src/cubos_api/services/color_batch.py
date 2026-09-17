"""Strict color-major expansion of one verified color campaign template."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

import yaml

from cubos_api.models.campaigns import CampaignSpec
from cubos_api.services.campaign_templates import compile_trial


_BATCH_COMMANDS = (
    "pick_up_tip", "transfer", "drop_tip",
    "pick_up_tip", "transfer", "drop_tip",
    "pick_up_tip", "transfer", "drop_tip",
    "pick_up_tip", "mix", "drop_tip",
    "move", "measure_color",
)
_DYE_STEPS = ((0, 1, 2), (3, 4, 5), (6, 7, 8))
_MIX_STEPS = (9, 10, 11, 12, 13)


@dataclass(frozen=True)
class BatchCompilation:
    protocol_yaml: str
    objective_paths: tuple[str, ...]
    sample_map: tuple[dict[str, Any], ...]


def _steps(protocol_yaml: str) -> list[dict[str, dict[str, Any]]]:
    document = yaml.safe_load(protocol_yaml)
    if not isinstance(document, dict) or set(document) != {"protocol"}:
        raise ValueError("Color batch template must contain only a protocol list")
    steps = document["protocol"]
    if not isinstance(steps, list):
        raise ValueError("Color batch template protocol must be a list")
    commands = tuple(
        next(iter(step)) if isinstance(step, dict) and len(step) == 1 else None
        for step in steps
    )
    if commands != _BATCH_COMMANDS:
        raise ValueError(
            "Color batch template must use the explicit 14-step color and "
            "dedicated-mix workflow; unsupported steps cannot be omitted"
        )
    if any(not isinstance(next(iter(step.values())), dict) for step in steps):
        raise ValueError("Color batch template command arguments must be mappings")
    return steps


def compile_color_trial_batch(
    base_protocol_yaml: str,
    spec: CampaignSpec,
    parameter_sets: list[dict[str, float]],
    start_index: int,
) -> BatchCompilation:
    """Compile up to six samples with one noncontact dye tip per stock."""
    # TODO(iter): test strict template rejection, partial batches, and exact
    # source/mix settings after the operator's offline batch review.
    if spec.batch_size <= 1:
        raise ValueError("Color batch compiler requires batch_size greater than one")
    if spec.source_protocol_file is None:
        raise ValueError("Color batch requires source protocol provenance")
    if spec.objective.mode != "result" or spec.objective.path != "13.delta_e_00":
        raise ValueError(
            "Color batch template requires a result objective at generated "
            "step 13 delta_e_00; other objective paths cannot be remapped"
        )
    if not parameter_sets or len(parameter_sets) > spec.batch_size:
        raise ValueError("Color batch must contain between one and batch_size samples")
    if (
        start_index < 0
        or start_index % spec.batch_size != 0
        or start_index + len(parameter_sets) > spec.stop.max_trials
    ):
        raise ValueError("Color batch sample range is outside the campaign plan")
    _steps(base_protocol_yaml)
    compiled = [
        _steps(compile_trial(
            base_protocol_yaml, spec.model_dump(), parameters, start_index + offset,
        ))
        for offset, parameters in enumerate(parameter_sets)
    ]
    destination_wells = [sample[1]["transfer"]["destination"] for sample in compiled]
    if len(set(destination_wells)) != len(destination_wells):
        raise ValueError("Each color batch sample requires a distinct candidate well")
    output: list[dict[str, dict[str, Any]]] = []
    dye_tips: set[str] = set()
    for pickup_index, transfer_index, drop_index in _DYE_STEPS:
        tip = compiled[0][pickup_index]["pick_up_tip"]["position"]
        if any(
            sample[pickup_index]["pick_up_tip"]["position"] != tip
            for sample in compiled
        ):
            raise ValueError("Each color uses exactly one shared tip per batch")
        if tip in dye_tips:
            raise ValueError("Red, yellow, and blue require separate tips")
        dye_tips.add(tip)
        output.append(copy.deepcopy(compiled[0][pickup_index]))
        source = compiled[0][transfer_index]["transfer"]["source"]
        for sample_index, sample in enumerate(compiled):
            transfer = sample[transfer_index]["transfer"]
            if transfer.get("source") != source:
                raise ValueError("A shared dye tip cannot switch stock sources")
            if transfer.get("destination") != destination_wells[sample_index]:
                raise ValueError("Color batch transfer destination is inconsistent")
            volume = float(transfer["volume_ul"])
            if not math.isfinite(volume) or not 0 < volume <= 200:
                raise ValueError("Each shared-tip dye transfer must be 0–200 µL")
            try:
                destination_height = float(transfer.get("destination_height", 0.0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Shared dye destination_height must be a finite number"
                ) from exc
            if not math.isfinite(destination_height) or destination_height < 0:
                raise ValueError(
                    "Shared dye tips require a nonnegative destination_height"
                )
            output.append(copy.deepcopy(sample[transfer_index]))
        output.append(copy.deepcopy(compiled[0][drop_index]))

    mix_tips: set[str] = set()
    objective_paths: list[str] = []
    sample_map: list[dict[str, Any]] = []
    for sample_offset, sample in enumerate(compiled):
        mix_tip = sample[_MIX_STEPS[0]]["pick_up_tip"]["position"]
        if mix_tip in dye_tips or mix_tip in mix_tips:
            raise ValueError("Each sample requires a fresh dedicated mix tip")
        mix_tips.add(mix_tip)
        well = destination_wells[sample_offset]
        if any(
            sample[index][command]["position"] != well
            for index, command in ((10, "mix"), (12, "move"), (13, "measure_color"))
        ):
            raise ValueError("Mix and color measurement must target the sample well")
        for index in _MIX_STEPS:
            output.append(copy.deepcopy(sample[index]))
        measurement_index = len(output) - 1
        objective_path = f"{measurement_index}.delta_e_00"
        objective_paths.append(objective_path)
        sample_map.append({
            "sample_index": start_index + sample_offset,
            "candidate_well": well,
            "parameters": dict(parameter_sets[sample_offset]),
            "measurement_step_index": measurement_index,
            "objective_path": objective_path,
        })
    return BatchCompilation(
        protocol_yaml=yaml.safe_dump({"protocol": output}, sort_keys=False),
        objective_paths=tuple(objective_paths),
        sample_map=tuple(sample_map),
    )
