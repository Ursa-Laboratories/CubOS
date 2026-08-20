# Scope: PANDA-BEAR imaging parity — shared Pawduino link, lighting instrument, camera capture

Date: 2026-08-20 (rev 2: camera capture + image_well added — full PANDA imaging parity)
Status: awaiting review (Alex)
Origin: PANDA-BEAR imaging port — everything PANDA-BEAR's imaging stack can do, runnable from CubOS protocol YAML and the Operator UI.

## Goal

1. **PawduinoLink** — one persistent, per-port serial transport shared by every
   instrument driver that talks to the PANDA-family Arduino (today:
   `PawduinoCapper`, `OpentronsPipette`; new: lighting). Fixes the latent bug
   where two live drivers on the same tty would double-open the port and reset
   the Arduino mid-session.
2. **`lighting` instrument type** — new interface + `pawduino` vendor exposing
   two channels: `white` and `contact` (red+blue), with the firmware's discrete
   brightness levels.
3. **`set_lights` protocol command** — lights sequenced as first-class YAML
   steps, independent of camera capture. Appears in the protocol editor
   automatically via the command registry.
4. **Manual light control in the Operator UI** — new API endpoint + small
   widget (no manual instrument-actuation surface exists today; this is the
   first).
5. **Camera capture** — FLIR (Spinnaker/PySpin) and OpenCV vendors for the
   existing `CameraInstrument` type, a `capture` protocol command persisting
   into the existing `camera_measurements` table, and a composed `image_well`
   command replicating PANDA's `actions/imaging.py` end-to-end (standard
   white-light shot and curvature Z-stack).

### PANDA-BEAR imaging parity checklist (what "all functionality" means)

From `panda_lib/hardware/imaging/` + `actions/imaging.py` (read-only source):

| PANDA capability | Covered by |
|---|---|
| FLIR high-res capture via Spinnaker/PySpin (`flir_camera.py`, `camera_utils.setup_camera`) | Phase 5 `flir` vendor |
| OpenCV USB-webcam fallback with camera auto-detect (`open_cv_camera.py`) | Phase 5 `opencv` vendor |
| Mock camera for dry runs (`MockOpenCVCamera`) | `offline=True` on both vendors (CubOS house pattern) |
| Camera selection by config (`camera_factory.py`) | registry.yaml vendor key (existing mechanism) |
| White-light well image: move to well at plate image height, white lights 5%, capture, lights off, retract safe (`image_well` standard path) | Phase 7 `image_well` standard mode |
| Curvature Z-stack: 11 steps × 0.2 mm descent, contact lights 50%, capture per step, `_z{z}_b{brightness}` labels (`image_well` curvature path) | Phase 7 `image_well` curvature mode (parameterized) |
| Structured image naming by experiment/project/campaign/well/label (`image_filepath_generator`) | Phase 6 path builder from `ProtocolContext` |
| Image files recorded against the experiment (`results.append_image_file`) | Phase 6 → existing `DataStore._log_camera` / `camera_measurements` table |
| Imaging failure never halts the run; camera always retracts to safe position | Phase 7 failure policy |
| Data-zone metadata overlay (`add_data_zone`, `panda_image_tools.py`) | Phase 7, `add_datazone` arg (open question 7) |
| Independent light control (white + contact, discrete levels) | Phases 1–4 |

---

## Phase 0 — PawduinoLink shared transport (PR 1, no behavior change)

### New: `packages/core/src/cubos/instruments/_shared/pawduino_link.py`

Modeled on PANDA-BEAR's single `ArduinoLink` (its lights/emag/line-break/
pipette all share one link; read-only source, never imported).

- `PawduinoLink.acquire(port, baud_rate, command_timeout) -> PawduinoLink` —
  class-level registry keyed by `port` string; same port ⇒ same instance.
  Conflicting `baud_rate` for an already-registered port raises.
- Refcounted lifecycle: `connect()` opens the tty once (first caller pays the
  Arduino DTR reset; discard boot banner + `CMD_HELLO` handshake, logic lifted
  from `OpentronsPipette.connect`), subsequent connects are no-ops;
  `disconnect()` closes only when the last holder releases.
- `send_command(command_id, *args, timeout=None) -> str` — one
  `threading.Lock` around each write→readline round-trip (the lock in
  `OpentronsPipette._lock` today protects the wrong scope: one instrument, not
  the port). Returns the raw `OK:`/`ERR:` line; raises `PawduinoLinkError` /
  `PawduinoLinkTimeout` on transport faults.
- No offline mode in the link. Offline stays where it is today: each vendor
  simulates in memory and never constructs a link (current
  `PawduinoCapper`/`OpentronsPipette` pattern, keep it).

### Modified

- `cubos/instruments/capper/vendors/pawduino.py` — replace `self._serial`
  management with an acquired link; wrap link errors into the existing
  `CapperConnectionError` / `CapperTimeoutError` / `CapperCommandError` so the
  `CapperInstrument` exception contract is unchanged.
- `cubos/instruments/pipette/vendors/opentrons.py` — same refactor; drop
  `_lock`, `_close_serial`, banner-discard (moves into the link).

### Tests

- New `tests/instruments/_shared/test_pawduino_link.py` (mock `serial.Serial`):
  same-port ⇒ same instance; refcounted close; single open/reset when two
  holders connect; two threads interleaving commands get non-corrupted
  request/response pairing; baud conflict raises.
- Existing `tests/instruments/capper/test_capper.py` and
  `tests/instruments/pipette/test_pipette.py` pass unmodified (or with
  mock-target renames only) — this is the "no behavior change" gate.
- New regression test: capper + pipette configured on the same `port` share
  one underlying serial open.

**Size:** ~350 LOC src + ~250 LOC tests.

---

## Phase 1 — `lighting` instrument type (PR 2, with Phases 2–3)

### New package: `packages/core/src/cubos/instruments/lighting/`

- `interface.py` — `LightingInstrument(BaseInstrument)`:
  - `channels: Mapping[str, tuple[int, ...]]` (property) — supported
    brightness percentages per channel, declared by the vendor.
  - `set_channel(channel: str, brightness_pct: int) -> None` (abstract) —
    unknown channel or unsupported level raises `LightingConfigError` listing
    the valid set (exact match, no snapping — see open question 1).
  - `all_off() -> None` (abstract).
  - `status() -> LightingStatus` — per-channel current level. Firmware has no
    readback for lights, so vendors shadow state in memory and reset the
    shadow to all-off on `connect()` (the DTR reset physically turns lights
    off, so shadow and hardware agree).
  - Lighting is non-positional: `offset_x/offset_y/depth` default 0; nothing
    targets it for motion. (Verify during implementation that no gantry math
    assumes every instrument is a motion target — camera/mount_only suggests
    this is already fine.)
- `models.py` — `LightingStatus` (pydantic).
- `exceptions.py` — `LightingError`, `LightingConfigError`,
  `LightingConnectionError`, `LightingCommandError` (mirror capper's tree).
- `vendors/pawduino.py` — `PawduinoLighting`, thin consumer of `PawduinoLink`:

  | channel | levels (pct) | on commands (`PawduinoFunctions`) | off |
  |---|---|---|---|
  | `white` | 5, 10, 15, 25, 50, 100 | 22, 21, 20, 19, 18, 17 | 2 |
  | `contact` | 5, 10, 20, 30, 50 | 27, 26, 25, 24, 23 | 4 |

  Command IDs from PANDA-BEAR `panda_lib/hardware/arduino_interface.py`
  (read-only source, same convention as the capper docstring). Bare
  `CMD_WHITE_ON=1` / `CMD_CONTACT_ON=3` (full/default brightness) are not
  exposed — the discrete table is the whole surface. `offline=True` simulates
  in memory like the other Pawduino vendors.

### Modified

- `cubos/instruments/registry.yaml` — new `lighting:` section (interface path
  + `pawduino` vendor), mirroring the `capper:` block.
- `services/api` instrument schema endpoints (`/instrument-types`,
  `/instrument-schemas`) introspect the registry — expected to pick the new
  type up with **no code change**; verify in tests.

### Tests

- New `tests/instruments/lighting/test_lighting.py`: interface validation
  (bad channel, bad level, error message lists valid levels), vendor sends
  exact command IDs (mock link), offline simulation, status shadow resets on
  reconnect, registry loads the vendor via `get_instrument_class`.

**Size:** ~300 LOC src + ~250 LOC tests.

---

## Phase 2 — `set_lights` protocol command

### New: `packages/core/src/cubos/protocol_engine/commands/lights.py`

- `@protocol_command` handler `set_lights`, args (pydantic-validated by the
  registry):
  - `instrument: str` — gantry instrument name.
  - `channel: str | None`, `brightness: int | None` — both required unless…
  - `off: bool = False` — `all_off()`; mutually exclusive with
    channel/brightness.
- `_get_lighting(context, name)` isinstance-gate against
  `LightingInstrument` — same pattern and error copy as
  `commands/capper.py::_get_capper`. No vendor branching in the command
  (house rule).
- Summary formatter (for the run view / editor): `"lights: contact 50%"`,
  `"lights: off"`.
- Register the module in `protocol_engine/commands/__init__.py` (the API
  imports `cubos.protocol_engine.commands` for side-effect registration —
  once registered, the command **automatically appears in the protocol
  editor's add-step dropdown** via `/api/v1/protocol/commands`).
- **Fail-safe:** run teardown (completion *and* abort/error paths in
  `protocol_engine/runtime.py`) calls `all_off()` best-effort on every
  `LightingInstrument` mounted on the gantry, so an aborted run never leaves
  contact lights on. Locate the same hook the capper's safe-retract path
  uses.

Example protocol YAML this enables:

```yaml
- set_lights: {instrument: lights, channel: contact, brightness: 50}
- move: {instrument: camera, position: well_A1}
- set_lights: {instrument: lights, off: true}
```

### Tests

- New `tests/protocol_engine/test_set_lights.py`: happy path, `off`,
  mutual-exclusion validation, wrong-instrument-type error, teardown
  all-off on abort, summary strings.

**Size:** ~150 LOC src + ~200 LOC tests.

---

## Phase 3 — Gantry config wiring

- `packages/core/configs/gantry/cub_xl_panda.yaml` — add a `lights:` entry,
  `type: lighting`, `vendor: pawduino`, `offline: true` initially (flip to a
  real `port:` at hardware bring-up; same port string as the capper/pipette
  entry once those go live — the link registry makes that safe).
- Update `packages/core/configs/README.md` instrument table.
- Loader (`gantry/instrument_loader.py`) is generic over registry types — no
  code change expected; covered by a loader test with a lighting entry
  (fixture config under `tests/fixtures/configs/gantry/`).

**Size:** config-only + 1 loader test.

---

## Phase 4 — Manual control: API endpoint + Operator UI widget (PR 3)

Today the UI actuates instruments only through protocol runs; there is no
manual-actuation endpoint (nothing for the capper either). This adds the
first one.

### API — `services/api/src/cubos_api/routers/gantry.py`

- `POST /api/v1/gantry/lights` — body `{instrument, channel, brightness}` or
  `{instrument, off: true}` (same shape as the command args; reuse the
  validation model).
- Uses `_require_session()`'s loaded gantry instruments; guarded by
  `_reject_if_run_active()` (manual toggling mid-run would fight the
  protocol's own `set_lights` steps — consistent with existing manual-motion
  guards).
- `GET /api/v1/gantry/lights` — `LightingStatus` per lighting instrument, so
  the widget can render current state.

### UI — `apps/operator-web/src/components/gantry/LightsControl.tsx`

- Renders only when the loaded gantry config has a `lighting` instrument
  (from the existing instrument listing).
- Per channel: level buttons from the vendor's declared `channels` map
  (served in status/schema payload — no hardcoded levels in the UI) + one
  "all off". Disabled while a run is active.
- Placement: gantry/manual panel next to the existing gantry widgets
  (open question 5).
- Mirror into `operator-desktop` only if it wraps operator-web (check at
  implementation; if it's a separate surface, defer with a TODO).

### Tests

- API: router test for both endpoints incl. run-active rejection and
  validation errors.
- UI: component test (render from mock instrument list, click → fetch call,
  hidden when no lighting instrument), added to the existing test suites.

**Size:** ~150 LOC API + ~200 LOC UI + tests.

---

## Phase 5 — Camera vendors: FLIR + OpenCV (PR 4)

### New: `packages/core/src/cubos/instruments/camera/vendors/flir.py`

`FlirCamera(CameraInstrument)`, ported from PANDA `flir_camera.py` +
`camera_utils.setup_camera` (acquisition-mode/exposure node setup):

- **PySpin is proprietary and not pip-installable** (Spinnaker SDK, manual
  install — see PANDA `imaging/README.md`). Lazy import behind an
  `is_available()` guard; constructing a non-offline `FlirCamera` without
  PySpin raises a config error whose message includes the SDK install
  pointer. Declare an extras group (`cubos[flir]`) that documents—not
  installs—the dependency.
- `connect()`/`disconnect()`/`health_check()` wrapping PySpin system +
  camera-list lifecycle (init, begin/end acquisition, release — the
  double-release segfault hazards handled in PANDA's `close()` carry over).
- `capture(save_path: str) -> str` — grab frame → numpy → write PNG →
  return the saved path (satisfies the existing
  `CameraInstrument.capture(*args, **kwargs) -> str` contract, and the
  data store's expectation that a camera result is an image-path string).
- `offline=True`: generate a placeholder image in memory and write it to
  `save_path` (parity with PANDA's `MockOpenCVCamera`, which synthesizes
  frames) so dry runs produce real files downstream code can open.

### New: `packages/core/src/cubos/instruments/camera/vendors/opencv.py`

`OpenCVCamera(CameraInstrument)` from PANDA `open_cv_camera.py`: `cv2`
capture with configurable `camera_id` and `resolution`, plus PANDA's
`detect_camera()` index auto-scan when `camera_id` is unset. Same
`capture(save_path) -> str` and offline behavior. `opencv-python` also as an
optional extra.

### Modified

- `registry.yaml` — `flir` and `opencv` vendors under the existing
  `camera:` section (joining `mount_only`, `raspberry_pi`).
- `pyproject.toml` — optional extras; core install stays dependency-free.

### Tests

- `tests/instruments/camera/test_flir.py` / `test_opencv.py`: offline
  capture writes a decodable image; missing-SDK error message; node-setup
  call sequence against a mocked PySpin; opencv auto-detect. Mirror
  `test_rpi_camera.py` conventions.

**Size:** ~450 LOC src + ~300 LOC tests.

---

## Phase 6 — `capture` protocol command + image storage (PR 4)

### New: `packages/core/src/cubos/protocol_engine/commands/camera.py`

- `@protocol_command` `capture` — args: `instrument`, `label: str | None`.
  Isinstance-gated on `CameraInstrument` (`_get_camera`, same pattern as
  `_get_capper`). No motion — capture happens wherever the gantry is, so
  YAML composes `move` + `set_lights` + `capture` freely.
- **Path builder** (`_image_path(context, label) -> Path`): CubOS
  equivalent of PANDA's `image_filepath_generator` — structured under the
  data directory from `ProtocolContext` campaign/experiment ids + label +
  timestamp; directory creation; collision-safe. Lives next to the command
  (or `cubos/data/results/` if reused by exports).
- **Persistence**: when durable tracking is active (same
  `context.data_store`/`campaign_id` gate the capper uses), log via
  `data_store.log_experiment_measurement` → existing `_log_camera` /
  `camera_measurements` table (`data_store.py:101` — already in schema, no
  migration). Without tracking: file still saved, path in the step summary.
- Summary formatter: `"capture: well_A1_after_dispense.png"`.
- Check `data/exports.py` includes `camera_measurements` in export packets;
  add if missing.

### Tests

- `tests/protocol_engine/test_capture.py`: happy path (offline camera →
  file exists, DB row), no-tracking path, wrong-instrument-type error,
  path-builder structure/collision behavior.

**Size:** ~200 LOC src + ~200 LOC tests.

---

## Phase 7 — `image_well` composed command (PR 5)

The PANDA `actions/imaging.py::image_well` equivalent — one YAML step for
the common case, composed from gantry + lighting + camera primitives in the
command layer (the capper precedent; nothing vendor-specific in the engine).

### New handler in `commands/camera.py` (or `commands/image_well.py`)

Args: `camera: str`, `lights: str`, `well: str` (labware target),
`label: str | None`, `mode: standard | curvature`, curvature params below,
`add_datazone: bool = False`.

- **standard** (PANDA parity): `move_to_labware` the camera over the well
  at imaging height → settle (~0.2 s) → white lights 5% → `capture` →
  lights off → record → retract to `safe_z`.
- **curvature** (PANDA parity): Z-stack descending from imaging height —
  PANDA hardcodes 11 steps × 0.2 mm at contact 50%; here parameterized
  (`z_step_mm=0.2`, `z_steps=11`, `channel=contact`, `brightness=50` as
  defaults) with per-step labels `"{label}_z{z}mm_b{brightness}"`.
- **Imaging height**: PANDA reads `wellplate.plate_data.image_height`.
  CubOS labware has no such field — add optional `image_height_mm` to the
  well-plate labware schema (deck YAML), required only by this command
  (clear error naming the field when absent).
- **Failure policy** (PANDA parity, matches its explicit comment "the image
  is not critical to the experiment"): capture/lighting failures log a
  warning and the run continues; the `finally` always retracts the gantry
  to `safe_z`. Gantry motion failures still fail the run (motion faults are
  never swallowed — consistent with capper fail-closed).
- **`add_datazone`**: port `panda_image_tools.add_data_zone` (PIL metadata
  overlay onto a copy saved as `*_dz.png`, both recorded). PANDA's overlay
  draws echem-experiment fields; the port takes generic run/campaign/label
  fields instead (open question 7). PIL joins the optional extras.

### Tests

- `tests/protocol_engine/test_image_well.py`: standard sequence order
  (mocked gantry/lights/camera call log), curvature step count/labels/z
  math, lights-off guaranteed after failure, retract-on-failure, missing
  `image_height_mm` error, datazone file pair.

**Size:** ~300 LOC src + ~300 LOC tests.

---

## Phase 8 — Manual capture in the Operator UI (PR 6, optional polish)

- `POST /api/v1/gantry/camera/capture` (`{instrument, label?}`, run-active
  guard) and `GET /api/v1/gantry/camera/last-image` serving the most recent
  capture for preview.
- operator-web: capture button + thumbnail preview alongside the Phase 4
  lights widget. `image_well`/`capture` already reach the protocol editor
  automatically via `/protocol/commands`, so this phase is only the
  outside-a-run convenience; can ship later without blocking parity.

**Size:** ~120 LOC API + ~180 LOC UI + tests.

---

## PR plan

1. **PR 1 — PawduinoLink + capper/pipette refactor.** Pure infrastructure,
   no behavior change; existing tests are the gate.
2. **PR 2 — lighting instrument + `set_lights` + configs** (Phases 1–3).
   Depends on PR 1.
3. **PR 3 — manual lights API + UI** (Phase 4). Depends on PR 2.
4. **PR 4 — camera vendors + `capture` command** (Phases 5–6). Independent
   of PRs 1–3 — can proceed in parallel.
5. **PR 5 — `image_well` composed command** (Phase 7). Depends on PRs 2
   and 4.
6. **PR 6 — manual capture UI** (Phase 8). Depends on PR 4; optional
   sequencing.

Each PR follows the repo conventions: vendor docstrings citing the PANDA-BEAR
source protocol, no vendor branching in engine/API code, offline simulation
parity, fail-closed error paths.

## Open questions for review

1. **Brightness matching** — exact-match against the firmware's discrete
   levels (recommended: explicit, editor can show the valid set) vs. snapping
   an arbitrary percentage to the nearest level.
2. **Channel naming** — `white` + `contact` (recommended; matches PANDA
   nomenclature) vs. `white` + `red_blue`.
3. **Auto lights-off on run end/abort** — scoped in (recommended). Say if you
   want lights to persist across run boundaries instead.
4. **Manual endpoint blocked during active runs** — scoped in (recommended).
5. **Widget placement** in operator-web (gantry panel assumed).
6. **OpenCV vendor** — scoped in for PANDA parity (their fallback camera).
   Drop it if FLIR + the existing `raspberry_pi` vendor cover all real
   hardware.
7. **Data-zone overlay fields** — PANDA's `add_data_zone` draws
   echem-experiment metadata. Proposed port overlays generic
   campaign/run/well/label/timestamp instead. OK, or defer the overlay
   entirely to analysis-side tooling?
8. **`image_height_mm` on labware** — adding an optional field to the
   well-plate deck schema (PANDA equivalent: `plate_data.image_height`).
   Any objection to it living on labware rather than the camera config?
   (Labware is where PANDA keeps it, and it's plate-specific.)
9. **Curvature-mode defaults** — parameterized with PANDA's values as
   defaults (11 × 0.2 mm, contact 50%). Confirm those are still the values
   you run.

---

## As built (2026-08-20, single PR)

All phases were implemented in one PR at Alex's direction. Deltas from the
plan above, discovered during implementation:

1. **`image_height` is a command argument, not a labware field.** CubOS's
   stated convention (see `BaseInstrument`'s docstring) is that
   labware-relative motion heights are first-class command arguments
   (`measurement_height` on `measure`/`scan`), never instrument or labware
   config. `image_well` follows it. Open question 8 resolved accordingly.
2. **`set_lights` uses `all_off: true`, not `off: true`.** YAML 1.1 parses a
   bare `off:` key as the boolean `false`, so `off` can never be a YAML arg
   name.
3. **Manual endpoints live under `/api/v1/instruments/...`** (new router),
   not under `/gantry`: lighting list/set, camera list/capture/last-image.
   Instruments only exist connected during protocol runs, so the router owns
   a manual-instrument cache built from
   `GantrySession.connected_gantry_config` (new public property), cleared on
   gantry connect/disconnect. Manual captures land in `<images>/manual/` and
   are deliberately not recorded in the data store (no campaign/well to
   attribute them to).
4. **Fail-safe lights-off lives in
   `InstrumentedGantry.disconnect_instruments`** — the single chokepoint
   every run path (complete or aborted) funnels through — rather than in
   per-path teardown hooks.
5. **Persistence needed no new code.** `DataStore._log_camera` /
   `camera_measurements` and the exports pipeline already handle image-path
   string results end to end; `capture` just logs the path via
   `log_experiment_measurement`.
6. **OpenCV vendor config uses `resolution_width`/`resolution_height`**
   (registry config fields must be primitives, not tuples).
7. **New gantry config `cub_xl_panda_imaging.yaml` + protocol
   `panda/imaging_demo.yaml`** — dry-run verified end to end (mock run: 6
   steps, 2 placeholder PNGs written, both recorded in
   `camera_measurements`, `camera.csv` exported). `safe_z` is 60.0 there,
   not 85.0: bounds validation showed `safe_z + camera depth (32)` must
   stay within `z_max` (100), which the copied-from config predates.
8. **Open questions 1-5, 8, 9 resolved as recommended** (exact-match
   brightness; `white`/`contact` naming; auto lights-off on; run-active
   guard on; widget in the gantry panel under the position widget; PANDA
   curvature defaults parameterized). Question 6: the OpenCV vendor was
   kept (cheap, and it is PANDA's fallback). Question 7: the data-zone
   overlay was **dropped from this PR** — it draws echem-experiment fields
   that have no CubOS equivalent yet; revisit when analysis-side needs it.
