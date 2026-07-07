# 06 — Calibration CLI UX polish (never lose operator work, prompts mean what they say)

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits, regression test per fix. Tasks 04 and 05 have landed — build on their state. Working tree has uncommitted in-flight edits to these files — build on top, never revert.

Scope: `setup/calibrate_gantry.py`, `setup/calibration/*.py`, `docs/calibration.md`, tests under `tests/setup/`.

## Fixes

1. **MEDIUM — the final pre-motion prompt starts calibration on ANY input, including "n"/"no".** `calibrate_gantry.py:133-134`: the return of `input_reader("Press ENTER to connect to hardware and start calibration, or Ctrl-C to abort: ")` only decides whether to print "Starting calibration..." — typed refusals proceed to connect and home, and pressing ENTER (the documented action) prints nothing while junk input prints the message. Fix: treat `n`/`no`/`q`/`abort` (case-insensitive) as abort; print the starting message unconditionally.
2. **MEDIUM — late-stage failures throw away 10–30 minutes of jog work.** The calibrated YAML is printed/written only AFTER GRBL soft-limit programming and verification: `single:1133` (`configure_soft_limits_from_spans`) precedes `_print_config_patch`/`_print_yaml_block` (`single:1143/1169`); `multi:791` precedes `multi:830`. A serial hiccup or "GRBL soft-limit settings did not verify" (`gantry.py:636-638`) ends the session with only an ERROR line and every measured value lost. Fix: print (and, when an output path is known, write) the computed YAML BEFORE programming soft limits; on late failure, tell the operator the file/values are already saved.
3. **MEDIUM — a block-height typo aborts the whole run instead of re-prompting.** `_calculate_block_z_calibration` raises `RuntimeError` ("Home-to-block travel exceeds the configured factory Z travel", `single:1066-1072`, `multi:638-644`) long after the prompt. Fix: validate the entered height against `factory_z_travel_mm` at prompt time and re-prompt on nonsense.
4. **MEDIUM — contradictory Z instructions in the single flow.** `_interactive_jog_to_xy_origin`'s confirmation text (`single:911-914`) describes deck-bottom/ruler Z modes, but the only supported entrypoint always runs `z_reference_mode="block"` (`calibrate_gantry.py:228`), and the preflight (`single:970-972`) correctly says to touch the reference top. Fix: parametrize the confirmation text by `z_reference_mode`.
5. **LOW — `--output-gantry` silently clobbers; in-place writes keep no backup.** The overwrite confirmation only covers the no-flag case (`calibrate_gantry.py:126-131`); with an explicit path `_maybe_write_gantry_yaml` short-circuits the confirm (`single:387-399`) and `write_text` overwrites (`single:401-402`). Fix: confirm when the explicit output exists and differs from the input; write a timestamped `.bak` beside any in-place overwrite.
6. **LOW — declining the overwrite confirm exits as an ERROR.** `calibrate_gantry.py:131` raises `RuntimeError` → "ERROR: ..." + exit 1 (`:278-280`). Fix: an intentional "no" exits 0 with a neutral message.
7. **LOW — docs/calibration.md jog section is stale.** `docs/calibration.md:113-124`: says holding a key "queues multiple jog commands" but the code batches repeats into one multiplied move (`single:761-762`, uncapped — consider capping the batch for ≥25mm steps); omits `SPACE — cancel any active jog` (the primary in-flow safety key, `single:773-776`); and the in-flight rewrite dropped the multi-CUB "disconnect other CUBs first" warning while auto-scan is still the only connection path (no `--port` flag). Also align the documented multi-flow prompt ORDER with the code (docs `:158-161` vs actual: reference instrument → height → ... → lowest instrument much later; docs never mention the up-front height prompt). Fix all four in the doc (or move the height prompt to just before the Step-2 touch where the dry-run text `multi:505-506` claims it happens — pick whichever is less invasive and keep docs+code+dry-run text consistent).

## Tests (minimum)

- "n"/"no" at the start prompt → no connect attempt, exit 0; ENTER proceeds with the message printed.
- YAML print/write happens before soft-limit programming (assert ordering via a scripted gantry whose `configure_soft_limits_from_spans` raises — the operator still gets the YAML).
- Out-of-range block height re-prompts instead of raising later.
- Explicit `--output-gantry` to an existing different file prompts; in-place overwrite leaves a `.bak`.
- Declined overwrite → exit code 0.

## Gate

`venv/bin/python -m pytest tests/setup -q`, then full suite green; `venv/bin/python -m mkdocs build --strict` (docs edits must not break the build — if mkdocs isn't installed in the venv, `venv/bin/python -m pip install -e '.[docs]'` first).
