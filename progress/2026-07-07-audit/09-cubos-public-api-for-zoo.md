# 09 — Public CubOS APIs for Zoo (kill the private-import seams)

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits, regression test per new API. Tasks 01–08 have landed — build on their state.

## Context

Zoo (`/Users/alexchan/Documents/Ursa/Zoo`, the web UI over CubOS) currently reaches into CubOS internals because no public API exists. This task adds the CubOS-side APIs only — Zoo's switchover is task 10. Design each export as a stable, documented, tested public surface (add to the owning package's `__init__`/`__all__`, docstring with types).

## APIs to add (each driven by a verified Zoo usage)

1. **Deck well preview.** Zoo imports privates: `from deck.loader import _derive_wells_from_calibration, _resolve_load_names` (`Zoo/zoo/routers/deck.py:12`, used at `:68`, `:113` for its `/preview-wells` endpoint). Add public `deck.derive_wells_preview(entry, resolved_z) -> Dict[str, Coordinate3D]` (thin wrapper over `_derive_wells_from_calibration`, `src/deck/loader.py:300`) and `deck.resolve_load_names(raw)`; export via `src/deck/__init__.py` `__all__`.
2. **Measurement-method reflection.** Zoo hardcodes CubOS's result-type dispatch table (`Zoo/zoo/routers/gantry.py:348-388` duplicates the isinstance set from `src/protocol_engine/measurements.py` and re-derives per-type methods via `inspect.getmembers`) — it silently misses any new result type. Add `instruments.registry.list_measurement_methods(instrument_type, vendor=None) -> list[str]` plus `protocol_engine.is_measurement_result(obj_or_cls) -> bool`, both built on the SAME type set `measurements.py` dispatches on (single source of truth — refactor measurements.py to expose the set rather than copying it).
3. **Calibration state.** Zoo reads private flags with a silent-false default: `getattr(session, "_calibration_jog_bypass_working_volume", False)` / `_calibration_restore_soft_limits` (`Zoo/zoo/routers/gantry.py:242-245`; attrs at `src/gantry/session.py:111-112`) — a rename would silently report "not calibrating" (safety-relevant). Add a public read-only `GantrySession.calibration_active: bool` property (true when either flag is set) with a docstring stating the contract.
4. **Labware config serialization.** Zoo hand-maintains per-type field lists (`Zoo/zoo/routers/deck.py:185-219` `_normalize_well_plate_config`/`_normalize_vial_config`), so new labware types get no normalization. Expose a public mapping in `deck.yaml_schema` from labware type string → its YamlEntry model (so a consumer can `model_fields`/validate per type), or a `to_config_summary()` on loaded labware — pick the shape that requires no Zoo-side field lists.
5. **Structured movement errors.** Zoo string-matches CubOS error fragments to choose HTTP 409 vs 400 (`Zoo/zoo/routers/gantry.py:280-290`: "require a loaded gantry working_volume", "checks require current gantry position"). Add a structured attribute (e.g. `requires_reconnect: bool`) or distinct subtypes on `MovementOutOfBoundsError`/relevant gantry errors (`src/gantry/errors.py`) covering the cases Zoo matches — enumerate the fragments in Zoo's `_movement_requires_operator_reconnect` and give each a typed home.
6. **Instrument config field metadata.** Zoo builds its instrument config forms by reflecting driver `__init__` signatures and hardcodes `pipette_model` choices (`Zoo/zoo/routers/gantry.py:309-334`). Building on task 07's signature validation, expose `instruments.registry.config_fields(instrument_type, vendor) -> list[FieldSpec]` (name/type/required/default/choices) derived from the driver signature + optional per-driver metadata.

## Notes

- Keep every wrapper thin — no logic changes to the wrapped internals.
- Update `docs/agent-index.md`/relevant docs pages with the new public names (AGENTS.md rule: docs update when cross-repo interfaces change).

## Tests

Each API: happy path + one edge (unknown type/vendor → clear error; `calibration_active` toggles with the session flags; `is_measurement_result` true for every type `measurements.py` persists, false for a plain dict... note dict IS persisted for potentiostat — match measurements.py exactly and encode that in the test).

## Gate

`venv/bin/python -m pytest tests/deck tests/instruments tests/protocol_engine tests/gantry -q`, then full suite green.
