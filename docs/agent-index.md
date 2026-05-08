# CubOS Agent Index

Use this as the first retrieval map for coding agents. Prefer repo source/docs over model memory, especially for hardware, YAML schema, protocol, and coordinate semantics.

## Start here

- Read `AGENTS.md` and `CLAUDE.md` before coding, then retrieve only the source/docs relevant to the subsystem below.
- For hardware-facing changes, include hardware impact, offline validation, and required physical validation in the PR.
- Hardware-facing validation order: focused offline/unit tests first, then give the user exact hardware tests before cleanup or broad test sweeps.
- For long, risky, or handoff-prone work, maintain a temporary checkpoint under `progress/`; small localized edits do not need one.

## Coordinate and motion semantics

Read these before changing gantry motion, coordinates, bounds, homing, scan movement, or protocol movement:

- `AGENTS.md` — hardware rules and current coordinate convention.
- `src/gantry/gantry.py`, `src/gantry/gantry_config.py`, `src/gantry/origin.py` — gantry frame, working volume, deck-origin calibration.
- `src/board/board.py`, `src/board/loader.py` — instrument offsets and labware movement.
- `src/validation/bounds.py`, `src/validation/protocol_semantics.py` — offline safety checks.
- `tests/protocol_engine/test_deck_origin_candidate_configs.py` — real config/protocol expectations.

Retrieval rule: do not infer sign flips from older code or model memory. Confirm current deck-frame convention in source and tests.

Bounds rule: working-volume validation is over labware motion targets, not
all geometry anchors. Holder bases and walls can be physical geometry only;
nested wells, slots, tip disposals, and other protocol-addressable targets are
what must be reachable.

## Deck YAML, labware, and calibration

Read these before changing deck configs, labware schemas, well position math, or validation messages:

- `src/deck/yaml_schema.py` — strict Pydantic YAML schema.
- `src/deck/loader.py` — load-name expansion, calibration, derived wells, nested labware.
- `src/deck/labware/` — runtime labware models.
- `src/deck/labware/definitions/` — reusable labware definitions.
- `configs/deck/` — real candidate deck YAMLs.
- `tests/test_deck_loader.py`, `tests/test_holder_labware.py`, `tests/test_panda_deck_yaml.py` — focused behavior gates.

Validation rule: after schema/config changes, run focused tests, full tests when practical, and `setup/validate_setup.py` for affected real gantry/deck/protocol triples.

## Protocol engine and setup validation

Read these before changing protocol YAML, protocol command args, setup loading, or semantic validation:

- `src/protocol_engine/yaml_schema.py`, `src/protocol_engine/loader.py`, `src/protocol_engine/setup.py`.
- `src/protocol_engine/commands/` for command behavior.
- `setup/validate_setup.py` for the end-to-end offline validation path.
- `configs/protocol/` for real protocol examples.
- `tests/protocol_engine/` for expected behavior.

Validation command pattern:

```bash
python setup/validate_setup.py <gantry.yaml> <deck.yaml> <protocol.yaml>
```

## Instruments

Read these before changing instrument drivers, mock behavior, or measurement persistence:

- `src/instruments/<instrument>/driver.py`, `mock.py`, `models.py`, `exceptions.py`.
- `src/instruments/registry.yaml`, `src/instruments/yaml_schema.py`.
- `src/protocol_engine/measurements.py`, `data/data_store.py` for persisted measurements.
- Relevant tests under `tests/instruments/`, `tests/protocol_engine/`, and `tests/data/`.

Hardware rule: if a change can touch a physical instrument, say what hardware validation remains.

## Config and docs updates

- If validation semantics change, search real configs/docs/examples for now-invalid patterns.
- If adding a fundamental feature, CLI argument, workflow, or semantic contract, update `AGENTS.md`, `README.md`, and relevant docs.
- Keep progress notes under `progress/` only for large, risky, hardware-facing, or handoff-prone tasks.

## Common verification gates

Use the smallest meaningful gate first, then broaden as risk requires:

```bash
python -m pytest tests/test_deck_loader.py tests/test_holder_labware.py -q
python -m pytest tests/protocol_engine -q
python -m pytest -q
python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi_indentation.yaml
```

Report exact commands and observed results in the PR body.
