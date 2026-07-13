# CubOS staging coordinate sync

Status: complete

## Scope

- Remove Zoo's separate mounted-instrument config workflow and use CubOS staging's gantry/deck/protocol runtime surface.
- Move mounted instrument editing into gantry YAML.
- Make position display and jog controls follow CubOS' deck-origin frame directly.
- Update gantry editing so missing current fields can be added and saved.
- Align deck orientation expectations with CubOS' calibrated A1/A2 resolver.

## Validation

- `PYTHONPATH=/Users/alexchan/Documents/hephaestus/CubOS/src python -m pytest tests -q` -> 34 passed.
- `npm run test` -> 3 files / 11 tests passed.
- `npm run lint` -> passed.
- `npm run build` -> passed.
- `git diff --check` -> passed.
- Stale active-reference grep for retired motion/config terms and removed UI/API surfaces -> no matches.

## Follow-up

- Connect now treats GRBL settings drift as a calibration warning instead of a
  connection failure. Zoo connects without passing expected `grbl_settings`
  into CubOS' live `Gantry.connect()`, then compares the selected gantry YAML
  against live controller settings and surfaces a persistent warning in the
  gantry control panel.
- Deck visualization now expands its display range from rendered deck,
  instrument, and gantry extents so labware that overhangs the configured
  working volume is not clipped.
