# CubOS system audit — 2026-10-13

Source reviewed: `main` at `38ccd0e7109926ac54cc90b018ff674161f87031`.
This is a source and offline behavior audit. It does not certify physical
safety or cover unmerged hardware/demo branches. No hardware, live machine
configuration, or appliance service was operated or changed.

## Coverage

| Area | Reviewed boundaries |
| --- | --- |
| Gantry and protocol runtime | Session locks, connection ownership, cached/live position, bounds and calibration gates, queued moves, interrupt/cancel, GRBL command/status paths, protocol compilation/execution, observers, pause/breakpoints, setup and teardown |
| Instruments, deck, validation | Mount translation, numeric/config schemas, bounds/semantics, calibration input helpers; representative connect/disconnect and error paths across camera, pipette, Pawduino, ASMI, UV/Vis, UV curing, Filmetrics, and potentiostat drivers |
| API, data, SDK | Host/origin/token boundary, request/path validation, run submission/recovery/events, SQLite state journals, reconciliation, result exports, settings/config I/O, client errors/timeouts |
| Operator web and desktop | Edit/preview state, raw YAML application, reconciliation state, jog interaction, polling/run state, desktop child lifecycle/readiness/navigation, config seeding |
| Packaging and maintenance | Python/Node manifests, CI gates, Docker entrypoint, Pi updater/rollback, Windows packaging/launch scripts, duplication and comments |

All areas were surveyed; review depth varied. Vendor SDK internals, actual
controller behavior, power-loss durability on appliance filesystems, a built
Windows installer, and a deployed ARM64 container were not validated.

## Changes in this PR

- Reject non-finite instrument mounting geometry in both YAML and Python
  constructors. Preserve signed finite offsets and vendor-specific fields.
- Reject non-finite working-volume bounds in YAML and the domain model before
  hardware construction. NaN bounds previously made comparisons fail open.
- Reject non-finite live gantry coordinates before jogging. Recheck bounds and
  calibration inside the queued Move To worker's operation lock.
- Reuse the existing atomic text writer for run records/artifacts. Recover only
  a malformed, unterminated final event after an interrupted append. Preserve
  its original bytes in `events.jsonl.partial`; complete or interior corrupt
  records still fail visibly. Continue event sequences from persisted values,
  and invalidate the sequence cache after a failed append.
- Only write wide UV/Vis CSV when wavelength values actually match; the long
  CSV retains each spectrum's own grid.
- Ignore non-object saved settings rather than crashing startup.
- Prevent outdated well-preview responses from replacing newer previews and
  bind reconciliation forms to the state for which they were opened.
- Reject foreign reconciliation operation keys at the API before mutating any
  fluid, tip, or cap journal, including requests naming a missing state.
- Reuse the shared calibration JogPanel, removing 168 duplicated lines including
  styles. Stop held jogging on touch cancellation in both calibration views.
- Handle desktop spawn failures, stream closure and readiness failures; compare
  parsed URL origins instead of string prefixes. Run desktop runtime tests in CI.
- Share protocol migration hints between YAML and Python compilation; remove
  stale UI-flow comments, duplicate mounting documentation, and unused code.

## Remaining findings

These are existing issues outside the bounded patch. They are not evidence
that the rest of a subsystem is safe. P1 means prioritize before relying on the
affected hardware workflow; P2 means a concrete correctness/reliability fix;
P3 means a lower-priority cleanup whose live consequence is unproven.

| Priority | Finding and evidence | Follow-up |
| --- | --- | --- |
| P1 | `protocol_engine/setup.py::_best_effort_retract_to_safe_z` uses the last **requested** instrument XY. `gantry/instrument_mount.py::move` records it before controller dispatch. A fake controller at `(10,20,30)` after a failed request for `(200,50,5)` received recovery target `(200,50,80)`. | Define a recovery policy using verified live position or no automatic movement when position is uncertain. Add failure-injection tests and operator validation before changing recovery motion. |
| P2 | `gantry/session.py::run_protocol` closes its store without `finish_campaign`. Both successful and failed fake runs left SQLite campaign status `running` and no finish time. | Close campaign metadata on every exit while preserving the primary run exception. |
| P2 | `services/api/src/cubos_api/services/run_manager.py::_execute` performs initial I/O before its cleanup `try/finally`. Injecting an `append_event` failure left the active-run reservation set. Cancellation transitions also require a concurrency review (static finding). | Put reservation release around the whole worker lifecycle; test initial I/O failures and cancel/start/finish races. |
| P1 | `data/data_store.py::_relax_asmi_metadata_columns` rebuilds a legacy table without a transaction. An injected SQLite failure at the final rename left one measurement stranded in `asmi_measurements_new`; reopening exposed an empty replacement table. | Make migration transactional and test recovery after every stage before upgrading databases needing this migration. Preserve the stranded table for recovery. |
| P2 | `routers/instruments.py` selects a manual camera filename before taking the capture lock. Inspection shows simultaneous same-label requests can choose the same destination. | Reserve the output path inside the serialized capture section; test concurrent requests. |
| P2 | Raw YAML editors accept nested shapes their renderers cannot handle: `DeckEditor` with `labware: {plate: null}`, `GantryEditor` with `{}`, and `ProtocolEditor` with `positions: {park: null}`. Source inspection; not exercised in a browser here. Protocol apply also updates steps before converting positions. | Validate render-required shapes before committing any local state, preferably through the existing core/API boundary; keep apply atomic. |
| P1 | `LabwareCalibrationModal` held-jog handling has unmount cleanup but no window blur/visibility stop handler, unlike `GantryPositionWidget`. Static finding; physical continuation was not tested. | Cover focus loss and touch cancellation across remaining held-jog controls, then validate operator stop behavior on an empty gantry. |
| P2 | `deck/labware/vial.py` and `labware.py` accept non-finite capacities/dimensions through comparison-only guards. Constructing a vial with NaN capacity and infinite height succeeded offline. | Apply field-specific finite validation and test volume/bounds consumers. |
| P2 | `single_instrument_calibration.py::_factory_z_travel_mm` and `_calibration_block_height_mm` return NaN for NaN input. Reproduced with helper calls; successful controller programming with such values has not been established. | Reject non-finite calibration dimensions before setup/controller actions and test valid dimensions. |
| P3 | `camera/vendors/opencv.py::connect` skips explicit capture release if property setup raises before ownership is assigned. A mocked `capture.set()` failure left `release()` uncalled even after disconnect. Actual SDK object destruction may release it. | Acquire/release ownership consistently and test setup failures. |
| P2 | `uv_curing/vendors/excelitas.py::cure` accepts NaN exposure offline; in the connected branch intensity is set before integer conversion fails, so this input does not reach `RUN`. Offline behavior reproduced; live ordering inspected, no UV hardware used. | Validate exposure finiteness before any instrument command and test rejected inputs with a fake transport. |
| P2 | `deploy/pi/update.sh` removes a lock when its PID file is absent. Inspection shows a second process can arrive between lock-directory creation and PID-file creation. Health-check curl also has no request timeout. | Use an atomic locking primitive suited to the Pi and test contention/process death; bound each health request. |
| P2 | Mount attributes remain mutable after construction. Assigning `instrument.offset_x = NaN` later passes comparison-only bounds checks and sends NaN to a mocked controller. The new constructor/schema guards do not cover mutation. | Validate transformed coordinates at the dispatch boundary, or make mounting geometry validated on assignment. |
| P3 | `sdk/python/src/cubos_client/client.py` computes polling sleep from the time remaining before the HTTP request. A slow request can make waiting exceed the requested deadline. Static finding. | Recompute remaining time after each response and test with a controlled clock; consider sharing duplicate request/error handling separately. |

Other complexity hotspots remain: large protocol semantics/fluid-state modules,
large editor/calibration components, repeated raw-YAML shape handling, and a
web bundle above Vite's 500 kB advisory threshold. Splitting these needs separate
behavior-focused changes, not blanket comment removal. Safety, units, geometry,
and vendor-quirk explanations should remain near their code.

## Offline verification

An isolated Python 3.12 environment has editable installs of core, API, and SDK.
Frontend dependencies use the checked-in lockfile. Exact final results are also
recorded in the PR description.

Results: 2,701 core tests passed (20 skipped), 358 API/SDK tests passed (2 skipped),
418 web tests passed, and 11 desktop tests passed. Core changed-line coverage was
100%. Web lint/build, strict documentation build, and offline setup validation
passed (195 motion targets checked). The web bundle-size advisory remains.

Production source has a net reduction of 180 lines; regression tests and this
audit report account for the overall increase. No runtime dependency was added.

- Core: `.venv/bin/python -m pytest packages/core/tests --cov=packages/core/src/cubos --cov-report=xml -q`
- Coverage: `.venv/bin/diff-cover coverage.xml --compare-branch=origin/main --fail-under=90`
- API/SDK: `.venv/bin/python -m pytest services/api/tests sdk/python/tests -q`
- Web: `cd apps/operator-web && npm run lint && npm run test -- --run && npm run build`
- Desktop: `cd apps/operator-desktop && npm test`
- Docs: `.venv/bin/mkdocs build --strict`
- Setup: `.venv/bin/python -m cubos.tools.validate_setup packages/core/configs/gantry/cub_xl_asmi.yaml packages/core/configs/deck/asmi_deck.yaml packages/core/configs/protocol/asmi/indentation.yaml`

Updater integration tests use throwaway Git repositories and stubs for installs,
network, and services. They were rerun outside the macOS sandbox because its
`/dev/fd` restriction blocked shell process substitution.

## Operator checks required before merge

Hardware potentially affected: gantries using manual jogging/Move To, calibration
jog controls, and any mounted instrument whose offsets are loaded. No physical
validation has been performed; keep the PR in draft until that is completed.

1. Use an empty, calibrated machine and its existing known-good configuration.
   Run the offline setup validator with that machine's gantry/deck/protocol files.
2. At a clear interior position at safe Z, record XYZ. Jog X +1 mm, then X −1 mm;
   verify direction, completion, and return to the starting position.
3. Move To a point 1 mm inward at the same Y/Z. Verify one move and the expected
   final position. Request X = `x_max + 1` at the same Y/Z; verify rejection and
   no motion.
4. Validate copies of the gantry YAML with one mount field or working-volume
   bound set to `.nan`, `.inf`, or `-.inf`; confirm rejection offline. Do not load
   these into a live session. Confirm the unchanged finite configuration passes.
5. In full gantry calibration's jog stage, choose a small 0.1–0.5 mm step. Hold
   touch jogging and cause an OS/browser interruption that emits `touchcancel`
   (or dispatch that event to the held button in browser developer tools).
   Verify stopping with no later movement. Repeat in Deck → Calibrate labware →
   Adjust positions; check normal taps and releases too. Exit full calibration
   normally and confirm its soft limits are restored.
6. Treat malformed telemetry and queue/calibration races as offline fault
   injection only. Do not provoke them on a real controller.

No aspiration, dispensing, tip pickup/ejection, UV exposure, recovery movement,
or vendor SDK behavior was physically verified.
