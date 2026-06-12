# Remove gantry homing_strategy

Issue: Ursa-Laboratories/CubOS#182

## Changed
- Removed `cnc.homing_strategy` from gantry YAML configs, fixtures, docs, and examples.
- Removed the `HomingStrategy` domain enum and `GantryConfig.homing_strategy` field.
- Kept gantry homing behavior on the standard GRBL `$H` command; homing is no longer configurable through gantry CNC YAML.
- Updated schema/tests so `homing_strategy` is now rejected as an unknown CNC key.

## Verification
- Focused tests: `139 passed, 6 subtests passed in 0.83s`.
- Full tests: `1255 passed, 17 skipped, 10 subtests passed in 7.54s`.
- `git diff --check`: passed.
