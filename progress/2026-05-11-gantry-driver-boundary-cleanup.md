# Gantry Driver Boundary Cleanup

Setup/calibration now routes through public `Gantry` APIs instead of importing
`Mill` or `gantry_driver` internals. `Mill` was narrowed to low-level GRBL
connect/send/status/move behavior; dead instrument-offset files and test-only
driver helpers were removed.

Validation passed:
- `python -m pytest -q` -> `1155 passed, 4 subtests passed`
- `python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi_indentation.yaml` -> `PASS`
- `git diff --check` -> clean

Hardware not touched. Physical smoke still needed for connection diagnostics,
calibration soft-limit toggling, WPos setup, homing, and motion command flow.
