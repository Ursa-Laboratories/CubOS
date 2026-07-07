# CubOS production-readiness audit — 2026-07-07

Full audit of CubOS (operator CLI/UX flows for setup → calibration → protocol build → run, driver/serial robustness, deck/instrument safety, data persistence, docs accuracy, Zoo API boundary). Each numbered file is a self-contained task prompt suitable for a `/goal` or `codex exec` run.

**Baseline before changes** (branch `new-docs`, uncommitted in-flight docs/calibration changes present): 1336 tests, all green (`venv/bin/python -m pytest -q`); coverage 80% total. Weakest modules: `setup/hello_world.py` 0%, `setup/home_gantry_config.py` 0%, `src/gantry/offline.py` 0%, `setup/validate_setup.py` 40%, `setup/keyboard_input.py` 41%, `src/gantry/session.py` 54%, `src/gantry/gantry_driver/driver.py` 55%, `src/protocol_engine/builder.py` 64%.

## Ground rules for every task

- Repo: `/Users/alexchan/Documents/Ursa/CubOS`, python: `venv/bin/python` (ad-hoc scripts need `PYTHONPATH=src:.`; pytest handles it via pyproject).
- The working tree has **uncommitted in-flight changes** (docs + calibration prompts + tests). Build on top of them. Never revert, stash, or commit anything.
- **Offline only**: never open a real serial port; all tests use mocks/offline mode. This code moves a physical CNC gantry — treat every behavior change to motion paths as safety-relevant and pin it with a test.
- Add regression tests for every fix. Gate for each task: its listed focused tests, then `venv/bin/python -m pytest -q` fully green.

## Execution order (files sharing code must not run concurrently)

| Wave | Files | Why grouped |
| --- | --- | --- |
| 1 | 01 (protocol validation), 04 (serial driver/session), 07 (instrument drivers), 11 (docs/hygiene) | Disjoint: validation+registry, src/gantry, src/instruments vendors, docs/configs-README |
| 2 | 02 (run lifecycle), 05 (calibration motion safety), 08 (deck config safety) | 02 after 01 (protocol_engine overlap); 05 after 04 (session.py/driver semantics); 08 after 07 (instruments/registry yaml load) |
| 3 | 03 (data persistence), 06 (calibration CLI UX) | 03 after 02 (setup.py, scan/measure); 06 after 05 (calibration scripts overlap) |
| 4 | 09 (CubOS public API for Zoo) | after 02/03/05/08 (touches deck, instruments registry, protocol_engine, session) |
| 5 | 10 (Zoo pin + boundary — runs in the Zoo repo), 12 (gantry/setup test sweep), 13 (protocol/deck/instrument test sweep) | 10 after 09; 12/13 last so tests pin FINAL behavior; disjoint test dirs |

## Status

| File | Scope | Status |
| --- | --- | --- |
| 01-protocol-validation-correctness.md | serial_transfer schema break, pause/breakpoint rejection, measure indentation gap, silent-pass validators, position arity | ✅ done (408 validation/PE tests) |
| 02-run-lifecycle-safety.md | Z-retract on failure, disconnect masking, mock-mode real-gantry trap, breakpoint TTY | ✅ done (1410 total) |
| 03-data-persistence-robustness.md | DB location, persistence exception holes, transactions, campaign status, CSV export on failure | ✅ done (1441 total; DB → ~/.cubos) |
| 04-serial-driver-hardening.md | feed-hold/stop realtime path, line framing, casing, reconnect state, calibration soft-limit restore | ✅ done (343 gantry tests) |
| 05-calibration-motion-safety.md | jog-cancel on abort, idle-wait before recorded reads, soft limits in multi flow, stdin flush, hello_world crashes | ✅ done (109 setup tests) |
| 06-calibration-cli-ux.md | confirm semantics, YAML-before-programming, overwrite backups, prompt wording, calibration docs sync | ✅ done (118 setup tests) |
| 07-instrument-driver-robustness.md | yaml extras swallowing, KLA hangs/Polyimide, Vernier 0.0N, Excelitas truncation, Thorlabs rc, pipette volumes | ✅ done (304 instrument tests) |
| 08-deck-config-safety.md | duplicate YAML keys, tip-rack placeholder calibration, row-direction chirality, loader error quality | ✅ done (237 deck/validation tests) |
| 09-cubos-public-api-for-zoo.md | derive_wells_preview, measurement-method reflection, calibration_active, labware serialization, structured errors | ✅ done (8 new public APIs) |
| 10-zoo-pin-and-boundary.md | Zoo repo: broken CubOS pin, dangling .pth, switch to new public APIs | ✅ done (Zoo: 205 passed) |
| 11-docs-and-repo-hygiene.md | ARCHITECTURE.md fiction, README paths, broken anchors, lost driver docs, stale bytecode dirs | ✅ done (mkdocs --strict green, docs CI added) |
| 12-test-coverage-gantry-setup.md | fake-serial GRBL double, driver/session gaps, setup-script coverage (0-41% modules) | ✅ done (driver 89%, session 81%, setup scripts 86-97%) |
| 13-test-coverage-protocol-instruments.md | compile-through-registry sweep, persistence resilience, vendor driver gaps, builder coverage | ✅ done (builder 98%) |

**Final state (2026-07-07): 1540 tests passing (baseline 1336), coverage 88% (baseline 80%), `mkdocs build --strict` green, canonical `validate_setup` PASS, Zoo backend 205 passing on the new public APIs.**

## Deliberately deferred (not in scope of the prompt files)

- **Rebuilding the virtual GRBL simulator** described by ARCHITECTURE.md: the sources were never committed (only stale `.pyc` from a deleted checkout). Task 12 adds a lightweight fake-serial GRBL test double for driver tests; a full simulator + viewer is a feature project, not an audit fix. ARCHITECTURE.md is retitled as a design proposal in task 11.
- **Hardware-validated fixes**: `configs/deck/asmi_deck.yaml` carries `z: 30.0 #actual 25` and a contradictory calibration comment — task 08 fixes the comment, but the value needs a bench re-measure.
- **Persisting tip-rack consumption across runs** (task 03 documents the limitation; a per-campaign rack-state table is a feature).
- **Merging `new-docs` → main and re-pinning Zoo to a released ref**: task 10 aligns the pins to a working state; the branch/release strategy is the user's call.
- **`configs/protocol/sterling/2_instrument_vial_scan.yaml` fails validation after the audit** (surfaced during task 08): the pipette park move now reports a Cub XL right-rail collision. This looks like a genuine pre-existing hazard the strengthened bounds/collision targets finally catch, but fixing it needs bench knowledge of the intended park position — re-measure and update the config on hardware.
