# 13 — Test coverage sweep: protocol engine, data, deck, instruments

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits. **Runs LAST (with 12): tests pin FINAL post-fix behavior.** Tasks 01–09 and 11 have landed and each added regression tests — audit coverage first (`pytest --cov`), then fill only the remaining gaps below. Do not weaken existing assertions; if a test reveals a genuine bug, fix the bug.

Baseline (pre-audit): `src/protocol_engine/builder.py` 64%; everything else in these areas ≥70% but with specific untested behaviors listed below.

## Scenarios that must be covered (skip any already pinned by tasks 01–09)

### Protocol engine / validation
- Compile-through-registry for EVERY registered command (the all-commands schema smoke test from task 01 — verify it exists and covers YAML + builder paths).
- `pause`/`breakpoint` through full `run_setup_validation`; `measure` indentation-depth offline rejection; unresolvable measure/scan targets → violations.
- `ProtocolBuilder` (64%): error paths — bad command name, schema violation with step context, `add_position` validation, `with_setup` misuse, `validate()`/`run()` on an empty protocol.
- Mid-scan exception → final gantry pose is safe_z (task 02 semantics); mock_mode never scans serial; failing-disconnect root-cause preservation.
- `inject_runtime_args` mis-declaration and `scan.plate` nested-holder path resolution (`plate_holder.plate`).

### Data
- Corrupt contents JSON / malformed ASMI dict resilience; NULL scalar persistence; campaign status transitions; `labware_key` on experiments; `register_labware` rollback; transfer source decrement + overfill warning; export-after-failure + atomic write; `CUBOS_DATA_DB_PATH` and unwritable-path error.

### Deck
- Duplicate-YAML-key rejection (deck/gantry/registry files); bare `ursa_tip_rack` load error; row-direction field; `.`-in-key rejection; wall corner-Z message; unknown-load_name vs missing-config-file messages.

### Instruments
- The per-vendor gap list from task 07's tests (verify each exists): KLA hung-process timeout + non-Polyimide `FilmetricsParseError`; Vernier `read()` False + connect-time SDK wrapping; Excelitas STM rounding/rejection + failed-handshake state; Thorlabs rc failures + call-before-connect; Opentrons volume validation; instrument YAML unknown-key rejection with did-you-mean.
- Instrument registry: unknown type/vendor error message quality; external registry overlay (`CUBOS_INSTRUMENT_REGISTRY_PATHS`) load path.

## Targets & gate

`src/protocol_engine/builder.py` ≥85%; every `src/protocol_engine`, `src/data`, `src/deck`, `src/instruments`, `src/validation` module ≥80% (vendor driver modules ≥75% — SDK-bound lines may be pragma'd only when they literally require the SDK/hardware). `venv/bin/python -m pytest -q` fully green; report before/after coverage per area (`venv/bin/python -m pytest -q --cov=src --cov-report=term`). Finish with the canonical end-to-end check: `venv/bin/python setup/validate_setup.py configs/gantry/cub_xl_asmi.yaml configs/deck/asmi_deck.yaml configs/protocol/asmi/indentation.yaml` → PASS.
