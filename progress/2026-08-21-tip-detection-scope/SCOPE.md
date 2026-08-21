# Tip-Presence Detection Scope

**Branch:** `feat/tip-detection` off `origin/feat/imaging-parity` (PR #299 still open as of 2026-08-21; rebase to main when it merges).
**Status:** IMPLEMENTED 2026-08-21 as PR #303 (both phases, recommended defaults). Offline validation complete (full suite + diff-cover 99%); bench validation of the line-break path and camera calibration still pending — see the PR's hardware-validation section.

## Problem

`cubos.data.tip_state` durably tracks what CubOS *believes* about every tip slot, seeded once from the deck YAML's `tip_present` map at session creation. Physical reality diverges: operators refill or swap racks mid-campaign, partial racks get loaded, tips are consumed by untracked runs, and a failed pickup leaves the pipette dry while the protocol continues aspirating air. There is no sensing of actual physical state and no verification that a pickup worked.

The selection side already exists and is sound: `begin_pick_up_tip` resolves `slot_id=None` to the first `status='available'` row in the durable DB (untracked runs use the in-memory `rack.tip_present`). So "pick what's actually available" reduces to **making the availability data true** — sensing plus reconciliation — not to new selection logic.

## Detection avenues evaluated

### (a) Camera rack scan (pre-run / on-demand)

Move the camera over the rack (same motion pattern as `image_well`), light it, capture top-down, classify presence per position with OpenCV. Tips read as bright circles/annuli on a regular grid; empty sockets read as dark holes.

- **Pro:** reconciles the *whole rack* in one operation; catches refills (marks slots available again), not just missing tips; produces an auditable image artifact.
- **Con:** needs pixel↔mm registration (an `mm_per_px` calibration at the scan height), lighting sensitivity, and a tuned threshold. FLIR is not plugged in on the bench and PySpin only exists in the 3.10 PANDA-BEAR venv, so real-frame validation is currently gated; the OpenCV webcam vendor or saved frames via the 3.10 venv are the near-term hardware paths.

### (b) Pawduino line-break verify (per pickup/drop)

Command id 7 on the shared Arduino link — the same beam sensor `PawduinoCapper.read_cap_present` reads. PANDA-BEAR historically used it to confirm a tip is on the pipette after pickup: an attached tip breaks the beam at the tool head.

- **Pro:** hardware exists and works on the bench today; binary and cheap (~one serial round trip); catches the highest-severity failure mode (dry pickup → silent bad chemistry); symmetric check on `drop_tip` (beam should clear) catches stuck tips.
- **Con:** verifies only the tip on the pipette — cannot scan a rack. Shared with the capper: a held cap also breaks the beam, so the check is only meaningful when the capper isn't holding (true during pipetting).

### (c) Both

Camera makes the rack map true; line-break makes each pickup trustworthy. They cover disjoint failure modes and share no code path, so "both" is really two independent features.

## Recommendation: (c), built as two phases

**Phase 1 — line-break verify (bench-ready now).** Highest value per line of code; validatable on `bear-den-panda` immediately.

1. `PipetteInstrument` gains `read_tip_present() -> bool | None` — `None` means "no sensor" (default implementation), keeping the protocol engine vendor-blind: it checks the capability, never the vendor. `OpentronsPipette` implements it via the shared `PawduinoLink` with command 7 (same parse as the capper's, hoisted somewhere shared or duplicated ~10 lines — I lean toward a small helper on `PawduinoLink`); offline mode simulates. `SartoriusPipette` inherits the `None` default.
2. `pick_up_tip` command: after `pipette.pick_up_tip()`, if the sensor is available and `verify_tip=True` (new command param, default True), read it. Absent → retry the same slot up to `verify_retries` (default 1, mirroring the capper's `capture_retries` pattern). Still absent → the slot physically has no usable tip:
   - **tracked:** resolve the journal op as `reconciled` with `final_slot_status='consumed'` and an auto detail ("line-break verify: no tip after N attempts"), then begin a fresh op on the next available slot and try again — bounded by `verify_slot_advance` slots (default 3) before raising `reconciliation_required` for the operator. This is the "select based on what's actually available" behavior at pickup time, fully auditable in the journal.
   - **untracked:** `rack.mark_tip_used(slot)` and advance the same way.
3. `drop_tip` command: after `pipette.drop_tip()`, sensor should read clear; still broken → mark op `reconciliation_required` and raise (a stuck tip needs an operator — no safe auto-recovery).

**Phase 2 — `scan_tip_rack` camera command (offline-first).**

1. New pure module `cubos/vision/tip_detection.py`: `classify_tip_rack(image_path, grid, params) -> dict[slot_id, bool | None]`. Grid registration from the rack's known `rows`/`columns`/tip coordinates plus an `mm_per_px` parameter on the command (calibrated once per rig at the scan height); per-cell classification by intensity/annulus heuristic with a confidence margin. Low-confidence cells return `None` and are treated fail-safe as *not available*. Pure function over a saved PNG → fully unit-testable with synthetic images (diff-cover friendly, no hardware).
2. New protocol command `scan_tip_rack(camera, rack, image_height, mm_per_px, lights=…, brightness=…, threshold=…)` — motion/lighting/capture composed exactly like `image_well` (heights live on the command, per house rules), then classify and reconcile. Image persists through the existing `camera_measurements` path.
3. New `tip_state.reconcile_tip_presence(connection, fluid_state_id, rack_key, presence)` (+ `DataStore` wrapper): refuses while any tip op is pending; flips only rows whose status is `available` or `consumed` (sensed-present → available, sensed-absent/uncertain → consumed); never touches `reserved`/`attached`/`reconciliation_required` rows — those belong to the journal. Untracked runs update the in-memory `rack.tip_present` instead. Each flip is auditable (detail names the scan image).
4. Bench tuning CLI `python -m cubos.tools.tip_scan_check <image> --rows 8 --columns 12 …` (sibling of `bench_check`) to iterate thresholds on saved frames without a protocol run.

Nothing new is needed in selection: once reconcile runs, `begin_pick_up_tip`'s existing next-available query and the untracked `next_available_tip()` do the right thing. No auto-scan inside `pick_up_tip` — protocol authors add a `scan_tip_rack` step (typically right after `home`); keeps motion explicit and the command composable.

## Decisions where I'd like your call

1. **Auto slot-advance on failed pickup verify** (Phase 1, item 2): auto-resolving the journal op and consuming the slot without an operator is new policy — I think the audit trail plus the bounded advance (default 3) makes it safe, but "always stop and reconcile" is the conservative alternative. Which do you want as default?
2. **Sensor abstraction location:** `read_tip_present()` on `PipetteInstrument` (recommended — engine stays vendor-blind, no cross-instrument reach into the capper) vs. reusing the capper instrument from the pipette command. The beam is physically one sensor on the shared head; two instruments reading command 7 over the same refcounted link is fine mechanically.
3. **Scan registration mode:** single-shot whole-rack with `mm_per_px` (recommended; one calibration number, one capture) vs. a per-position mode (camera visits each tip, classifies the center patch — no calibration, but ~96 moves ≈ minutes per rack). Could ship single-shot first and add per-position only if calibration proves fiddly on the real rig.

## Validation plan

- **Offline (both phases):** unit tests for verify/retry/advance flows with mock pipettes (sensor present, absent, unsupported), `reconcile_tip_presence` guard cases, and classifier tests on generated synthetic rack images. Gates: `pytest packages/core/tests/protocol_engine packages/core/tests/data -q`, then full suite + diff-cover ≥90%.
- **Bench (Phase 1, ready now):** on `bear-den-panda`, real pickup/drop with the beam sensor — verify true-positive, then an empty-slot pickup to watch the advance path. Pawduino on `/dev/ttyACM0` is shared with lights — the refcounted link already handles that.
- **Bench (Phase 2, gated):** FLIR is unplugged; capture tuning frames via the OpenCV webcam vendor or the 3.10 PANDA-BEAR venv, iterate with `tip_scan_check`. Camera code paths run offline (placeholder PNGs) until then.

## Files touched (estimate)

Phase 1: `instruments/pipette/interface.py`, `instruments/pipette/vendors/opentrons.py`, `instruments/controllers/pawduino.py` (shared line-break parse), `protocol_engine/commands/pipette.py`, `protocol_engine/yaml_schema.py`, tests. Phase 2: `vision/tip_detection.py` (new), `protocol_engine/commands/` (new command), `data/tip_state.py`, `data/data_store.py`, `tools/tip_scan_check.py` (new), tests. Docs: `docs/protocol-yaml.md` for the new command/params.
