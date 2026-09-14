# Potentiostat Rinse handoff

Adds `rinse(instrument, vial, measurement_height)` as a protocol command.
The depth is a negative millimeter offset from the calibrated vial rim.
The command dips and retracts three times and finishes at `safe_z`.

## Hardware validation

Hardware affected: the gantry and mounted potentiostat probe. No real
hardware has been connected or actuated during development.

Before merge, an operator must test on the intended station:

1. Verify the probe mounting offset, vial-rim calibration, travel clearance,
   uncapped vial, rinse-liquid level, and probe clearance from the bottom.
2. Create a single-step protocol using the example in `docs/protocol-yaml.md`,
   substituting the actual instrument, vial path, and verified negative depth.
3. Run `python -m cubos.tools.validate_setup <gantry.yaml> <deck.yaml> <rinse.yaml>`.
4. With the operator at the stop control, run
   `python -m cubos.tools.run_protocol <gantry.yaml> <deck.yaml> <rinse.yaml>`.
5. Confirm exactly three immersions and withdrawals, no rim/bottom contact,
   and the final probe position at `safe_z` above the vial.
6. Record the station, exact files and command, observed behavior, and any
   untested behavior in the PR before merge.

Offline test results are recorded in the PR. Physical clearance, immersion,
and actual rinse effectiveness remain unverified.
