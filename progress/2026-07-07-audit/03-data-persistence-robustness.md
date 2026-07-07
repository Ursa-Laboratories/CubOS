# 03 — Measurement data persistence robustness

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits, regression test per fix. Tasks 01/02 have landed — build on their state.

## Goal

Measurement persistence must never abort a healthy hardware run, never lose data it could have saved, and store data somewhere that survives reinstalls.

## Fixes

1. **HIGH — a corrupt DB row aborts a hardware run.** `commands/measure.py:130-139` and `scan.py:191-200` guard persistence with `except (TypeError, sqlite3.Error)` only, but `data/data_store.py:614-618` (`get_contents`) raises `ValueError` on corrupt contents JSON and `src/protocol_engine/measurements.py:166-170` raises `KeyError` on malformed ASMI dicts. Persistence here is explicitly best-effort (results still return to the caller) — broaden the guards to `except Exception` with a loud log.
2. **MEDIUM — default DB lives inside the installed package.** `data/data_store.py:26` → `Path(__file__).parent/"databases"/panda_data.db`: read-only on system installs, silently discarded on reinstall/upgrade; `DataStore()` is created unconditionally (`setup.py:196-200`) so a `PermissionError` kills the run before it starts. Fix: default to a user-data dir (`~/.cubos/panda_data.db`), keep the `CUBOS_DATA_DB_PATH` override; on creation failure raise a clear error naming the path and the env override. Migrate: if the old package-dir DB exists and the new default doesn't, log a pointer (don't move files silently).
3. **MEDIUM — `campaigns.status` is dead metadata (always `'running'`).** `data_store.py:37`; no `UPDATE campaigns` exists anywhere, so a crashed run is indistinguishable from a completed one. Fix: add `DataStore.finish_campaign(campaign_id, status, finished_at)` and call it from `run_on_hardware`'s finally with `'completed'`/`'failed'`.
4. **MEDIUM — experiments are keyed by labware display *name* while contents/dispenses use the deck *key*.** `scan.py:184-189` (`labware_name=plate_obj.name`), `measure.py:123-127`; `deck/loader.py:425` allows `name=entry.name or plate_key`, and `mock_asmi_deck.yaml` already diverges — measurement rows can't be reliably joined to labware state. Fix: add a `labware_key` column to experiments (keep the display name), populate it from the deck key, include it in exports.
5. **MEDIUM — `register_labware` partial writes.** `data_store.py:526-548` does per-well inserts with one commit at the end; a mid-loop exception leaves pending rows that the next unrelated `commit()` silently persists; `data/protocol_runs.py:63-66` catches only `TypeError`. Fix: wrap in an explicit transaction (`with self._conn:`); broaden the protocol_runs guard consistently with fix 1.
6. **MEDIUM — one-sided volume tracking.** `commands/pipette.py:196-199` records the dispense into the destination but never decrements the source, and nothing checks `working_volume_ul`/`capacity_ul`. Fix: decrement the source row in `transfer`/`serial_transfer` (they know `source_key`), and log a warning when a dispense would exceed the destination's working volume (no hard failure — hardware already moved).
7. **LOW — ASMI measurements missing scalar metadata are silently dropped.** `measurements.py:181-183` fills `step_size_mm`/`z_target_mm`/`force_limit_n` via `.get()` (None), `data_store.py:250-252` `float(None)` → TypeError → classified "not persistable" and only warned; columns are NOT NULL (`data_store.py:94-96`). Fix: make the columns nullable (they're metadata) so real force curves are never discarded.
8. **LOW — orphan experiment rows.** `create_experiment` + `log_measurement` are two separately committed writes (`measure.py:123-129`). Fix: a transactional `log_experiment_measurement` helper.
9. **LOW — result CSVs export only on full success, non-atomically.** `setup/run_protocol.py:94-104`: any run exception exits before `export_campaign_results_csvs`; the export call sits outside the try/except (uncaught disk-full traceback); `data/exports.py:439-441` truncates in place. Fix: export whenever a campaign_id exists (partial data after a crash is exactly what the operator wants), wrap export errors with a clear message, write via temp file + `os.replace`.
10. **LOW — document the tip-rack re-run limitation.** `pipette.py:163-171`: rack consumption is in-memory only, so a re-run happily re-validates `pick_up_tip` against physically emptied slots. Add a prominent docstring/docs note (persisting rack state is deferred — see INDEX).

## Tests (minimum)

- Corrupt contents JSON row + malformed ASMI dict during measure/scan → run completes, loud warning, results returned.
- `CUBOS_DATA_DB_PATH` honored; default path is under the user dir; unwritable path → actionable error.
- Campaign status transitions to completed/failed (including mid-run exception).
- experiments row carries the deck key; register_labware mid-loop failure rolls back atomically.
- transfer decrements source volume; overfill logs a warning.
- Missing ASMI scalars persist as NULL; export after a failed run produces CSVs; export write is atomic (temp+replace observable via mocked os.replace).

## Gate

`venv/bin/python -m pytest tests/data tests/protocol_engine tests/setup -q`, then full suite green.
