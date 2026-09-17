# Active-learning campaigns

Choose **Workflow → Active Learning** to optimize numeric protocol arguments over repeated native CubOS runs. The **Protocol** tab retains the single-run workflow. Campaign **Setup**, **Run**, and **History** share the existing Gantry, Deck, State and Results workspace.

## Configure a campaign

1. Select and save your calibrated gantry and working deck in the existing tabs. In campaign mode, select a saved **Protocol template**.
2. Add named parameters with a minimum, maximum, positive step size and bindings to numeric protocol arguments. One parameter can control several arguments. Steps are displayed starting at 1; saved JSON uses zero-based indexes. Nested dotted argument paths are supported by the API.
3. For repeated liquid handling, add target sequences for fresh tip slots and destination wells. Bind the same destination sequence to every step that uses that trial's well. Each sequence must cover the trial budget; pickup targets must be distinct across the entire campaign. Do not repeat a tip or silently reuse a filled well.
4. Optionally select a group of parameters and a fixed sum, for example red/yellow/blue volumes totaling 300 µL.
5. Choose expected improvement (EI), lower confidence bound (LCB), or the seeded random baseline. Choose a Matérn 5/2 or RBF kernel, then set exploration and random seed. An optional ordered initial design runs before model-selected trials. Each point must contain every campaign parameter, lie on the configured quantized grid, and satisfy the mixture constraint.
6. Choose a numeric result path and minimize/maximize direction, or manual observations. Paths are relative to `RunRecord.result`: for example `results.0.thickness_nm` for a hardware run result, or `0.thickness_nm` for the offline example's result list. Missing, nonnumeric or nonfinite values stop the campaign before another trial. The `measure_color` command captures a centered circular ROI, converts median sRGB to CIE Lab, and returns `delta_e_00` when given a target `reference_lab`.
7. Choose trial budget, optional target value, patience with minimum improvement, and optional wall-time limit. Time limits are checked **between trials**; they do not cut a liquid-handling step short.
8. Select offline mock or real hardware explicitly. Real fluid-handling campaigns require an existing **fluid state ID**, created and seeded in State. The same durable state is reused across all trials. The mock mode cannot modify real fluid state.
9. **Validate**, then **Start campaign**. Editing a draft does not alter an already-running campaign's stored specification or setup snapshots.

## Observe and stop

The server submits one native run at a time, waits for it to finish, extracts its objective and feeds that observation into the next proposal. Proposal bounds and protocol semantics are checked before each trial. The trial table records parameter values, objective, native run ID and outcome. Use **Open run** to inspect progress and artifacts; use the regular Results and State views for native persisted hardware measurements and consumables.

- **Pause after trial** completes the active run and pauses before another proposal.
- **Stop after trial** completes the active run and ends the campaign.
- **Cancel run** requests native cancellation/feed hold for the active run and prevents subsequent trials. Inspect the native run/controller status before recovery; cancellation is not automatic motion resumption.
- A missing objective, invalid proposal or failed native run stops the loop. Search exhaustion, trial budget, target achievement and patience are recorded as stop reasons.

The station is reserved for the campaign, including between trials and while paused/awaiting observation. Setup mutations and unrelated run submissions are rejected; emergency hold/cancel remain available. Stop the campaign before manual movement or calibration. Switching views or closing the browser does not stop the server-owned campaign. A server restart marks unfinished campaigns **interrupted** and never automatically resumes hardware.

Campaign records and immutable gantry/deck/protocol snapshots live under `<run_dir>/campaigns/<campaign_id>/`. Child runs use the normal run store. The editor draft is stored locally in the browser; started campaign records remain on the server.

## Offline example

`examples/active-learning/` contains a mock-only gantry, deck, measurement protocol and campaign JSON. Copy the YAMLs into your isolated config directory as `bo_demo_gantry.yaml`, `bo_demo_deck.yaml`, and `bo_demo_protocol.yaml`. The mock Filmetrics adapter returns 150 nm on each run: this deliberately demonstrates feedback collection and automatic patience stopping, not physical optimization or improvement.

Use parameter `height`, bounds 0–10, step 1, bound to step 1 `measurement_height`; objective `0.thickness_nm`, minimize; initial trials 2; seed 7; max trials 8; patience 2. Keep **Offline mock** selected. It completes three native offline trials and stops with `no_improvement`.

## Color-matching experiment

Select the saved source protocol, target well, three stock vials, camera, sampling radius, and candidate wells. **Capture target** creates a visible native run and moves the camera. Review that saved image, select the intended well, and reanalyze it. Once the image passes its checks and a reconciled inventory is selected, **Build campaign** writes a generated protocol and fills the campaign draft. Selecting a region or reanalyzing a saved image does not move hardware.

The campaign creates three 50–200 µL parameters constrained to 300 µL per sample, with six initial recipes followed by expected-improvement proposals. The selected source protocol supplies the transfer heights, mixing settings, speeds, and other supported command arguments. For example, protocol 03's stock offset −20 mm and mixing settings of 60 µL, three cycles, and −7 mm are retained. The source must contain the supported three-stock pickup/transfer/drop sequence with mixing before the final drop; unsupported extra steps are rejected rather than discarded.

### Six samples per batch

New color setups default to **6 samples per batch**. CubOS proposes six recipes, then executes one native protocol: one red tip transfers red to all six wells, one yellow tip transfers yellow to all six, and one blue tip transfers blue to all six. Each dose is a separate transfer using the normal pipette capacity checks. Each well then receives a fresh mixing tip and its own camera measurement. A full batch uses nine tips; an 18-sample campaign uses three batches and 27 tips. A shorter final batch uses three dye tips plus one mixing tip per sample.

Shared dye tips must stay out of sample liquid. Negative destination-height offsets are rejected for batched transfers; zero means the calibrated well reference. Verify that this reference provides physical liquid clearance. Tip allocation follows the actual available inventory and side-exit accessibility, including consumption by earlier batches.

Every sample retains its own well, recipe, objective path, measurement status, and score even though it shares a native run ID with its batch. The optimizer uses completed accepted observations before proposing the next batch. **Pause after batch** and **Stop after batch** finish the active batch; **Cancel** interrupts it. A partially executed batch is not replayed automatically. Resolve uncertain tip/fluid state before attempting further work.

Saved YAML presets include `batch_size` and `source_protocol_file`. Existing presets remain single-sample until explicitly updated. Loading a preset clears target evidence and live inventory selection. Rebuild from a reviewed target and current inventory; old generated protocols and started campaign snapshots are not rewritten. Existing generic campaigns without batch settings retain their single-sample execution behavior.

Color setup supports two target modes. **Camera** uses an accepted target capture and its matching processing profile; **RGB** uses an operator-selected nominal sRGB triplet converted with CubOS's authoritative sRGB-to-Lab D65 function, so it is a digital reference and carries no camera-calibration claim. RGB mode skips target photography, while candidate camera measurements still require the detected-well, ROI, acquisition, and quality checks; the default expected center is the camera frame center and remains an explicit assumption rather than physical well identity. Saved presets retain the selected target mode and RGB value.

`examples/active-learning/color-target-protocol.yaml`, `color-matching-protocol.yaml`, and `color-matching-campaign.json` remain reviewable file-level examples for the 2026-09-14 checkpoint configs. The integrated UI performs the same setup without manual Lab copying. Set the real fluid-state ID and confirm the stock, plate, tip, camera, waste, and clearance targets before validation. Candidate results retain RGB, Lab, ΔE00, and ΔE76 beside the optimization objective.

Keep camera geometry, lighting, focus, exposure, white balance, and gain fixed for the target and every candidate. The default sampling radius is 50% of the detected well radius around the operator-selected region. Image checks exclude clipped pixels and glare and reject inadequate exposure; camera Lab remains an uncalibrated estimate. Prepare and image the target first; the optimizer receives its Lab value, not its recipe.

API endpoints: `GET/POST /api/v1/campaigns`, `POST /validate`, `GET /{id}`, and `POST /{id}/pause`, `/resume`, `/stop`, `/cancel`, `/observation` (finite `value`). Submit/validate bodies wrap the configuration in `{"spec": ...}`. A native numeric objective and explicit target sequences are required for fully automatic experimental campaigns; manual observations intentionally wait for the operator.

## Hardware validation status

Development verification uses isolated mock runs and injected fake run managers. No real motion, pipetting or protocols were executed by the implementation task. Before a hardware campaign, an operator must validate the target capture and one generated candidate against calibrated labware, confirm fresh consumables and stock volumes, verify the returned Lab/ΔE00 and objective path, then run a short supervised campaign and check stopping/cancellation and state conservation.
