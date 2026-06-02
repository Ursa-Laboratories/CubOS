# Agent Retrieval Index

Use this map after reading `AGENTS.md`. Read the smallest relevant set of files for the task.

## Gantry / motion / coordinates / homing

Read before changing motion, coordinates, bounds, homing, or scan/protocol movement.
- `src/gantry/gantry.py`, `gantry_config.py`, `origin.py` - frame, working volume, deck-origin calibration.
- `src/gantry/machine_geometry.py` - built-in fixed-structure AABBs per gantry family, including the `cub_xl` right-rail guard. Not user-authored YAML; consumed by setup validation.
- `src/gantry/coordinate_translator.py`, `instrument_mount.py`, `instrument_loader.py`, `loader.py`, `yaml_schema.py`, `grbl_settings.py`, `calibration_utils.py`, `offline.py` - gantry boundary, mounted instrument offsets, GRBL calibration utilities, and labware movement.
- `src/validation/bounds.py`, `src/validation/protocol_semantics.py` - offline safety checks, including fixed-structure rail collision.
- Tests: `tests/protocol_engine/test_deck_origin_configs.py`.

Setup and calibration flows should route through public `Gantry` APIs. Do not import `Mill` or `gantry_driver` internals from user-facing scripts.

Gantry YAML requires top-level `gantry_type` (`cub` or `cub_xl`). For `cub_xl`, setup validation rejects protocols whose instrument point or known travel segment would hit the fixed right X-max rail.

Setup bounds validation checks the concrete motion targets implied by the loaded protocol, not every physical geometry anchor or unused labware point on the deck.

## Deck YAML / labware / calibration

- `src/deck/yaml_schema.py` - strict Pydantic schema.
- `src/deck/loader.py` - load-name expansion, calibration, derived wells, nested labware.
- `src/deck/labware/`, `src/deck/labware/definitions/`.
- `configs/deck/`.
- Tests: `tests/test_deck_loader.py`, `tests/test_holder_labware.py`, `tests/test_panda_deck_yaml.py`.

After schema/config changes: focused tests, then `setup/validate_setup.py` for affected real triples.

## Protocol engine / setup validation

- `src/protocol_engine/yaml_schema.py`, `loader.py`, `runtime.py`, `setup.py`.
- `src/protocol_engine/commands/` - command behavior.
- `setup/validate_setup.py` - end-to-end offline validation.
- `configs/protocol/<instrument-or-workflow>/`.
- Tests: `tests/protocol_engine/`.

## Instruments

- `src/instruments/<instrument>/driver.py`, `mock.py`, `models.py`, `exceptions.py`.
- `src/instruments/registry.yaml`, `src/instruments/yaml_schema.py`.
- `src/protocol_engine/measurements.py`, `data/data_store.py` - persisted measurements.
- Tests: `tests/instruments/`, `tests/protocol_engine/`, `tests/data/`.

## Calibration scripts

- `setup/calibrate_gantry.py` - only supported user-facing calibration entrypoint. Loads input gantry YAML, dispatches single- or multi-instrument flow by instrument count. Without `--output-gantry`, prompts before overwriting input; with it, writes the explicit path without extra prompt.
- `setup/calibration/single_instrument_calibration.py` - internal one-instrument flow.
- `setup/calibration/multi_instrument_calibration.py` - internal multi-instrument flow.
- Detailed operator steps and offset math live in `docs/calibration.md`.

## Setup scripts

- `setup/validate_setup.py` - offline gantry+deck+protocol bounds/semantics validation. PASS/FAIL.
- `setup/run_protocol.py` - load, validate, connect hardware, run protocol end-to-end. Connects gantry after clearing expected GRBL alarm and restoring state, connects instruments before first step, and disconnects in `finally`.
- `setup/hello_world.py` - interactive deck-origin jog test. Homes without rewriting WCS, then jogs in the deck frame. Arrow keys (X/Y +/-1mm), Z (down 1mm), X (up 1mm), Q (quit).
- `setup/keyboard_input.py` - single-keypress reader using Unix `tty`/`termios`.

## Exception handling patterns

These rules apply everywhere in `src/` and `setup/`:

- `except Exception` in user-facing pipelines: include the exception type name in the error message so developers can diagnose without a full traceback, for example `f"{type(exc).__name__}: {exc}"`. Add `logging.getLogger(__name__).debug(..., exc_info=True)` for config-load failures; use `logging.exception` for unexpected failures in validators.
- Unguarded validation calls: wrap calls to validators, bounds checkers, or semantics checkers that can raise so callers get a structured result or a clear re-raised message instead of raw operator tracebacks.
- `MillConnectionError`: never catch and discard; always re-raise. Tests must explicitly cover propagation at every place a hardware exception is caught.
- Broad substring matching: avoid bare tokens like `"failed"` in status-parsing functions. Name the exact sentinel strings and verify they do not match unrelated production status strings.
- Post-jog status probes: if a probe raises after a successful jog, separate its exception handler from the jog handler and emit a distinct message. Do not report the jog itself as failed when only the probe failed.

## Testing patterns

- `MillConnectionError` propagation: for every `except MillConnectionError: raise` in hardware code, add a test that injects a `MillConnectionError` at that call site and asserts it propagates unchanged out of the top-level function.
- Error-stage routing: for any function that returns a result object with a `stage` field, each distinct stage value must have at least one test that triggers it and asserts `result.stage == "<stage>"`.
- Negative cases for status-matching functions: parametrize healthy status strings such as `"<Idle|WPos:0,0,0>"` and `None` alongside positive cases to prevent regressions from broadened token matching.
- Validation-engine failures: use `monkeypatch` to make validator functions raise and verify the calling pipeline returns a structured error result rather than propagating the raw exception.
