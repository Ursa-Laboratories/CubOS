# Agent Retrieval Index

Use this map after reading `AGENTS.md`. Read the smallest relevant set of files for the task.

## Gantry / motion / coordinates / homing

Read before changing motion, coordinates, bounds, homing, or scan/protocol movement.
- `src/gantry/gantry.py`, `gantry_config.py`, `origin.py` - frame, working volume, deck-origin calibration.
- `src/gantry/machine_geometry.py` - built-in fixed-structure AABBs per gantry family, including the `cub_xl` right-rail guard. Not user-authored YAML; consumed by setup validation.
- `src/gantry/coordinate_translator.py`, `loader.py`, `yaml_schema.py`, `grbl_settings.py`, `offline.py`.
- `src/board/board.py`, `src/board/loader.py` - instrument offsets and labware movement.
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

- `src/protocol_engine/yaml_schema.py`, `loader.py`, `setup.py`.
- `src/protocol_engine/commands/` - command behavior.
- `setup/validate_setup.py` - end-to-end offline validation.
- `configs/protocol/`.
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
