# Eight-channel calibration and geometry

Adds measured head envelopes and end-nozzle reference semantics for 8-channel
pipettes. X rows use the leftmost tip; Y rows use the frontmost tip. Existing
single-channel calibration and offset math are retained.

Hardware affected: mounted pipette, gantry carriage, calibration references,
and fixed-structure protocol validation. No physical hardware was connected.

Physical validation remains pending. Follow the eight-channel acceptance
procedure in `docs/calibration.md`; use measured hardware dimensions, not the
synthetic test fixture. Do not run the blocked collision fixture on hardware.
User authorized autonomous implementation and a PR for their later testing.

Offline gates and exact results are recorded in the PR. Delete on merge.
