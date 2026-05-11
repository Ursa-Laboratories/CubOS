# 2026-05-08 SHARC UV Holder Checkpoint

## Scope

- Add a reusable SHARC 80 mm SBS wellplate holder definition.
- Add a SHARC UV deck and UV curing scan protocol.
- Allow `scan` and protocol semantic validation to target a nested well plate such as `plate_holder.plate`.

## Hardware Impact

- Affects SHARC gantry XY/Z movement over a nested SBS plate.
- Affects OmniCure UV curing exposure when the new protocol is run on hardware.
- No hardware commands have been run in this coding pass.

## Validation

- `python -m pytest tests/test_holder_labware.py tests/protocol_engine/test_scan_command.py tests/validation/test_protocol_semantics.py -q` passed: 71 tests.
- `python -m pytest tests/test_holder_labware.py tests/protocol_engine/test_scan_command.py tests/validation -q` passed: 106 tests.
- After splitting geometry anchors from motion targets, `python -m pytest tests/test_holder_labware.py tests/protocol_engine/test_scan_command.py tests/validation -q` passed: 111 tests.
- `PYTHONPATH=src python -c "from deck.loader import load_deck_from_yaml; from protocol_engine.loader import load_protocol_from_yaml; ..."` confirmed `plate_holder.plate.A1` resolves to `(15.0, 17.0, 89.5)` and the SHARC protocol parses with `plate: plate_holder.plate`.
- The same parse check now confirms `plate_holder` exposes 96 motion targets and the protocol uses `instrument: uv_curing`.
- `git diff --check` passed.
- `python setup/validate_setup.py configs/gantry/cub_sharc.yaml configs/deck/sharc_uv_deck.yaml configs/protocol/sharc_uv_curing_scan.yaml` passed.
- `python setup/validate_setup.py configs/gantry/cub_sharc.yaml configs/deck/sharc_uv_deck.yaml configs/protocol/sharc_uv_motion_scan.yaml` passed.
- `python -m pytest tests/protocol_engine/test_deck_origin_configs.py -q` passed: 6 tests, including a guard that the SHARC motion-only protocol does not call `uv_curing.cure()`.

## Open Risks

- Assumes holder bottom/base is deck-frame Z=0.0 and plate surface/rim is Z=89.5.
- Assumes the active gantry config has a `uv_curing` instrument of type `uv_curing`, vendor `excelitas`.
- `configs/gantry/cub_sharc.yaml` now uses `safe_z: 101.5`, matching `working_volume.z_max`.
