# Scope

Implement protocol validation for pipette tip state and attached-tip geometry.

# Changed Files

- `src/validation/protocol_semantics.py`, `src/validation/bounds.py`
- `src/deck/labware/tip_rack.py`, `src/deck/yaml_schema.py`
- `src/board/board.py`, `src/instruments/pipette/driver.py`
- `src/protocol_engine/commands/pipette.py`
- `configs/sim/pipette_tip_transfer/`
- Focused docs and tests

# Validation

- Defaulted `TipRack.tip_length` and deck YAML `tip_length` to 59.3 mm for the
  current Opentrons 300 uL tips; tests now use that shared constant instead of
  smaller synthetic tip lengths.
- `python -m pytest tests/validation/test_pipette_tip_state.py -q` PASS
- `python -m pytest tests/validation/test_pipette_tip_state.py tests/protocol_engine/test_pipette_commands.py -q` PASS
- `python -m pytest tests/test_deck_loader.py tests/test_tip_rack_labware.py tests/protocol_engine/test_deck_origin_configs.py -q` PASS
- `python -m pytest tests/validation/test_pipette_tip_state.py tests/validation/test_bounds_validation.py tests/validation/test_protocol_semantics.py tests/validation/test_machine_structures.py tests/validation/test_safe_z.py -q` PASS
- `python -m pytest tests/validation/test_pipette_tip_state.py tests/protocol_engine/test_pipette_commands.py tests/instruments/pipette/test_pipette.py tests/test_deck_loader.py tests/protocol_engine/test_current_movement_contracts.py -q` PASS (`203 passed`)
- `python -m pytest tests/validation/test_machine_structures.py tests/validation/test_pipette_tip_state.py -q` PASS (`22 passed`)
- `python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi_indentation.yaml` PASS
- `python setup/validate_setup.py configs/gantry/cub_xl_sterling.yaml configs/deck/panda_deck.yaml configs/protocol/sterling_vial_scan.yaml` PASS
- `python setup/validate_setup.py configs/gantry/cub_xl_sterling_3_instrument.yaml configs/deck/panda_deck.yaml configs/protocol/sterling_2_instrument_vial_scan.yaml` PASS
- `python setup/validate_setup.py configs/gantry/cub_xl_sterling_3_instrument.yaml configs/deck/panda_deck.yaml configs/protocol/sterling_vial_scan.yaml` PASS
- `python -m pytest -q` PASS (`1213 passed, 4 subtests passed`; escalated only for the existing `~/.cubos/logs` gantry log write)
- `python setup/validate_setup.py configs/sim/pipette_tip_transfer/gantry.yaml configs/sim/pipette_tip_transfer/deck.yaml configs/sim/pipette_tip_transfer/protocol.yaml` PASS

# Hardware Impact

Validation-only changes can block or allow real gantry and pipette motion. No hardware commands are run in this pass.

# Open Risks

- Need physical confirmation for configured tip extension and pickup/drop heights before using on hardware.
- The offline simulation fixture uses the official Opentrons 300 uL tip length
  (59.3 mm), but the deployed Ursa rack should still be measured before real
  hardware runs.
- `configs/sim/pipette_tip_transfer/gantry.yaml` is still an offline simulation fixture; its photo-derived
  pipette mount offset should not be treated as a calibrated hardware setup.

# Next Steps

- Measure real `tip_length` for each deployed tip rack and update hardware deck YAML before pipette protocols are run.
