# ADE active-learning color matching

Status: application changes are deployed to the Raspberry Pi on branch `ADE` through `5e02d8290`. Target capture and one physical campaign trial have completed. The campaign is stopped after a recoverable result-extraction error and can now continue from trial 2 through the UI.

## Station access and safety

- Pi repository: `/home/cub/CubOS`
- Pi Python: `/home/cub/CubOS/.venv/bin/python`
- Live configs: `/home/cub/cubos-data/configs`
- Operator service: `cubos`, normally forwarded to `http://127.0.0.1:8742/`
- Simulator service: `cubos-routing-sim`, Pi port `8760`
- Connect with `ssh -o HostKeyAlias=cubos.local cub@10.193.33.24` using the existing key.
- Do not automatically home, jog, resume, or start a physical protocol. Use CubOS for hardware access and leave the final movement action to the operator.
- The controller `$27=0.5` versus selected gantry config `homing_pull_off: 2` mismatch remains unresolved. CubOS reports the calibration warning after connection.
- The operator service was restarted after the latest deployment. The most recent API check showed no active protocol and the gantry disconnected; click **Connect** before attempting to resume.
- Immediately before that restart, the gantry reported Idle at work position `(34.803, 116.535, 66.5)`.

## Implemented and deployed

- General active-learning/DOE campaign editor with numeric parameters, protocol bindings, sequences, ordered initial design points, mixture constraints, stop limits, and EI/LCB/random acquisition.
- Matérn 5/2 optimizer support.
- Center-ROI median RGB conversion to CIE Lab plus CIEDE2000/CIE76 results.
- `measure_color` protocol command and routed camera support.
- Integrated color-matching setup: select the target well, stocks, camera, candidate wells, and read the target from the same Active Learning view. The generated protocol and complete campaign draft remain visible/editable there.
- Target Lab values and their generated protocol location are visible in the UI.
- Browser JSON Lab arrays are accepted by the strict API model.
- Fluid-state tracking is optional for campaigns. Omitting a fluid-state ID avoids routing v1's unsupported durable-resume path.
- Campaign objective extraction now accepts both result representations used by CubOS: a top-level step-result list in mock mode and a hardware result wrapper containing that list under `results`.
- A failed campaign whose last native run succeeded can now be recovered with **Resume campaign**. Recovery scores the completed run, preserves that observation, and continues at the next trial/well instead of repeating the mixture.

Relevant ADE commits, oldest to newest:

- `52cb71a` — add color-matching active-learning campaigns
- `73b662c` — integrate target setup into campaigns
- `92a68c1` — accept browser target measurements
- `ae2b843` — show saved target color
- `f73a9e4` — read campaign objectives from run results
- `8a00954` — allow campaigns without fluid-state tracking
- `472ec25` — handle wrapped hardware campaign results
- `5e02d82` — resume campaigns after recoverable scoring errors

## Current experiment state

- Generated protocol: `/home/cub/cubos-data/configs/protocol/ade_color_matching_438892e7.yaml`
- Target well: `plate.A1`
- Captured target Lab: `(67.44549955394078, -4.620077403688915, 12.330453428107212)`
- Dye stocks: red `stocks.A1`, yellow `stocks.A2`, blue `stocks.A3`
- Candidate wells: `plate.A2` through `plate.A7`, then `plate.B1` through `plate.B12`
- Mixture bounds: 50–200 µL per dye, 5 µL grid, fixed 300 µL total
- Target: minimize ΔE00 to `<= 3`
- Objective path in the UI: `11.delta_e_00`
- Campaign ID to resume: `d6ba2e4d2fa9459cad6739feb3324f06`
- Trial 1 native run: `d6ba2e4d2fa9459cad6739feb3324f06-trial-1`
- Trial 1 completed physically in `plate.A2`: red 200 µL, yellow 50 µL, blue 50 µL.
- Trial 1 measured RGB `(123, 121, 114)`, Lab `(50.804827179452985, -0.59353825092201, 4.103951696294672)`, ΔE00 `16.524261796856912`, and ΔE76 `18.99474467760282`.
- Trial 1 image: `/home/cub/.cubos/images/campaign_12/color_candidate_20260915-130401.tiff`
- The native run succeeded. The campaign stopped only while extracting the objective because real hardware returned `{..., "results": [...]}` while mock mode returned `[...]`. No trial 2 movement occurred.

To continue, connect the gantry in the UI, select campaign `d6ba2e4d2fa9459cad6739feb3324f06` in Campaign History, inspect the physical setup, then click **Resume campaign**. It should score the saved trial 1 at ΔE00 `16.524261796856912` and begin trial 2 in `plate.A3` using the next tip set. Do not click **Start campaign**, because that creates a new campaign and repeats trial 1 in `plate.A2`.

## Validation and backups

Earlier focused validation before hardware iteration:

- 53 core optimizer/color/camera-command tests passed.
- 46 focused API campaign/route tests passed.
- 7 campaign UI tests passed; TypeScript, ESLint, and the production build passed.
- The station candidate protocol passed setup validation with 33 targets and 32 immutable routing plans.
- The 18-trial campaign passed server preflight in offline mode.

For the final fluid-state and result-recovery fixes, tests were deferred at the user's explicit request. The latest operator production build completed successfully on the Pi. Add regression coverage for wrapped hardware results and failed-campaign recovery before preparing a PR.

Pi code backups made before deployment:

- `/home/cub/cubos-backups/2026-09-15-before-stateless-campaign/code.bundle`
- `/home/cub/cubos-backups/2026-09-15-before-objective-wrapper/code.bundle`
- `/home/cub/cubos-backups/2026-09-15-before-campaign-resume/code.bundle`

The local untracked `services/api/configs/deck/cub_deck.yaml` and `work/` directory predate the final changes and were intentionally left untouched.
