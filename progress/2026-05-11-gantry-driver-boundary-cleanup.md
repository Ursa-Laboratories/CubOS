# Gantry Driver Boundary Cleanup

## Scope

Clean up the setup/calibration abstraction leak so setup scripts use the public
`Gantry` API instead of `Mill` or `gantry_driver` internals. Remove dead
driver-level instrument-offset/reference code so low-level GRBL send/query
details stay behind `Gantry`. Remove test-only `Mill` convenience methods and
dead constants that no longer have production callers.

## Changed Files

`src/gantry/`, `setup/`, `tests/setup/`, focused gantry driver tests, and the
hardware WPos test script.

## Validation

- `python -m pytest tests/setup/test_architecture_boundaries.py tests/setup/test_connection.py tests/setup/test_calibrate_deck_origin.py tests/setup/test_calibrate_multi_instrument_board.py tests/gantry/test_gantry.py tests/gantry/driver/test_gantry_driver.py tests/gantry/driver/test_wpos_enforcement.py tests/gantry/test_coordinate_translator.py -q`
  - Result after dead-code removal: `125 passed, 4 subtests passed in 1.11s`.
- `python -m pytest tests/gantry/driver/test_gantry_driver.py tests/gantry/driver/test_wpos_enforcement.py tests/setup/test_architecture_boundaries.py -q`
  - Result after test-only method removal: `34 passed, 4 subtests passed in 0.62s`.
- `python -m py_compile tests/hardware/test_wpos_enforcement.py`
  - Result: clean.
- `python -m pytest -q`
  - Result after test-only method removal: `1155 passed, 4 subtests passed in 2.55s`.
- `python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi_indentation.yaml`
  - Result: `PASS`.
- `git diff --check`
  - Result: clean.

## Hardware Impact

Potentially affects gantry connection diagnostics, calibration soft-limit
toggling, WPos setup, and low-level movement command generation. No hardware
has been touched in this refactor session.

## Open Risks

Physical calibration flow still needs operator validation. No hardware was
touched during offline validation.

## Next Steps

Run the hardware smoke procedure before trusting this on a real gantry.
