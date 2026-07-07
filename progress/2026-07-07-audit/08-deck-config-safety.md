# 08 — Deck & config ingestion safety (what you wrote is what drives the gantry)

Read `progress/2026-07-07-audit/00-INDEX.md` "Ground rules" first. Repo `/Users/alexchan/Documents/Ursa/CubOS`, `venv/bin/python`, offline only, no commits, regression test per fix. Task 07 has landed (instruments yaml extras validation).

Scope: `src/deck/**`, `src/gantry/loader.py` (YAML load path only), `src/instruments/registry.py` (YAML load path only), `configs/deck/*`, tests.

## Fixes

1. **HIGH — duplicate YAML mapping keys are silently last-wins.** `yaml.safe_load` everywhere (`deck/loader.py:496`, `instruments/registry.py:146`, definition configs, gantry YAML): a copy-pasted `plate:` block with an unrenamed key silently discards the first (measured) calibration and drives the gantry with the stale one — every validator passes. Fix: a shared `SafeLoader` subclass whose `construct_mapping` raises on duplicate keys, used for ALL deck/gantry/instrument-registry/definition loads (put it somewhere importable by all three, e.g. a small `cubos` yaml util module; keep error messages naming the file and the duplicated key).
2. **HIGH — the tip-rack definition ships absolute deck coordinates that silently apply.** `src/deck/labware/definitions/ursa_tip_rack/TipRack.yaml:22-27`: a deck entry of just `tips: {load_name: ursa_tip_rack}` loads with A1=(111.9, 2.7, 191.0) — placeholder coordinates on real hardware. Well plates are protected because their definition calibration lacks `z` (loader raises, `deck/loader.py:109`); the tip rack's Z comes from the definition's `pickup_z: 191.0`. Fix: strip `calibration`/`pickup_z` from the definition YAML and make the loader require per-deck values with a clear message ("definition provides geometry only; measure and set calibration/pickup_z in your deck YAML").
3. **MEDIUM — row direction is hard-wired chirality the YAML cannot express.** `deck/loader.py:278,291`: `row_step = -entry.y_offset if col_step > 0 else entry.y_offset` — two calibration points along the column axis can't determine which side row B is on, so the loader guesses; a plate whose rows advance +Y with columns +X gets every non-A row wrong by `2·pitch·row_idx`, and bounds validation still passes. Additionally, the exported `generate_wells_from_offsets` (`deck/labware/well_plate.py:154-187`) uses the OPPOSITE convention (always `+y_offset·row_idx`). Fix: add an optional explicit row-direction field (or accept a third calibration point, e.g. B1) to `WellPlateYamlEntry`, defaulting to current behavior; document the default convention in the deck schema docs; reconcile or clearly document the divergence between the two public well-generation paths.
4. **LOW — labware keys containing "." load but can never be resolved.** `deck/deck.py:54-57`: key `plate.1` loads; `resolve_coordinate("plate.1")` fails with `KeyError: "No labware 'plate' on deck."`. Fix: reject `.` in `DeckYamlSchema.labware` keys at load time.
5. **LOW — walls with omitted corner Zs produce a baffling error.** `deck/loader.py:462,467`: both default to 0.0 → "corner_1.z must be < corner_2.z". Fix: require explicit Z on `WallYamlEntry` (or default corner_2.z to a positive height) and make the message say what to set.
6. **LOW — missing definition config file misreported as unknown load_name.** `deck/loader.py:152-159` conflates `ValueError`/`FileNotFoundError` from `load_definition_config` (`definitions/registry.py:74-76`), listing the very name the user typed as "supported". Fix: separate unknown-name vs missing-config-file messages.
7. **LOW — config hygiene.** `configs/deck/asmi_deck.yaml:11-13`: header comment contradicts the data (a1=(347,42), a2=(338,42) share Y and differ in X; comment claims the opposite) — rewrite the comment to describe what the loader actually derives; leave `z: 30.0 #actual 25` in place but upgrade the comment to a visible `# TODO: re-measure on hardware (bench note says 25)`. Delete the no-op `WellPlateHolderYamlEntry._validate_single_nested_plate` (`deck/yaml_schema.py:295-299`) or implement it for real.

## Tests (minimum)

- Duplicate key in deck YAML, gantry YAML, and registry YAML each → load error naming file+key.
- Bare `load_name: ursa_tip_rack` (no per-deck calibration) → clear load error; with per-deck calibration → works.
- Explicit row-direction field honored both ways; default matches current derivation (pin with the existing loader tests, which encode the current convention).
- `plate.1` key rejected at load; wall missing Z gets the actionable message; missing-config-file vs unknown-load_name messages differ.
- All shipped `configs/` combos still pass `setup/validate_setup.py` (the INDEX lists the canonical combo; also spot-check `configs/deck/panda_deck.yaml` loads).

## Gate

`venv/bin/python -m pytest tests/deck tests/validation -q`, then full suite green, then the validate_setup PASS above.
