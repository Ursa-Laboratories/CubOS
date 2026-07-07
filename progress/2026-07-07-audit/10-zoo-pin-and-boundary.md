# 10 — Zoo: fix the CubOS pin and switch to the new public APIs

**This task runs in the Zoo repo: `/Users/alexchan/Documents/Ursa/Zoo`.** Python: Zoo's `.venv`. No commits; never revert unrelated working-tree changes. CubOS task 09 has landed in `/Users/alexchan/Documents/Ursa/CubOS` (branch `new-docs`, uncommitted) — the new public APIs exist there.

## Context (verified)

- `Zoo/pyproject.toml:11` pins `cubos @ git+...@codex/python-protocol-builder`, but Zoo's code calls the 2-arg `get_instrument_class(type_key, vendor)` (`zoo/routers/gantry.py:310, :382`) which only exists on CubOS `new-docs` — Zoo is a TypeError against its own declared pin.
- `Zoo/requirements.txt:17` pins a DIFFERENT ref (`@main`).
- Zoo's `.venv` resolves CubOS via a dangling `cubos-local.pth` pointing at `/Users/alexchan/Documents/hephaestus/CubOS/src` (deleted checkout) — the venv cannot import cubos at all right now. (Known gotcha: reinstall with `.venv/bin/python -m pip install -e /Users/alexchan/Documents/Ursa/CubOS`.)

## Steps

1. **Repair the environment**: remove the dangling `cubos-local.pth`; `.venv/bin/python -m pip install -e /Users/alexchan/Documents/Ursa/CubOS`. Verify `.venv/bin/python -c "import deck, gantry, protocol_engine"`.
2. **Align the pins**: point BOTH `pyproject.toml` and `requirements.txt` at the same ref — `new-docs` (the branch the audit fixes live on; it's a strict superset of `codex/python-protocol-builder`). Leave a `# TODO: repin to a tagged release once new-docs merges` comment. (Branch/release strategy beyond this is the user's call — note it in your summary.)
3. **Switch private imports to the task-09 public APIs**, deleting the Zoo-side duplicates:
   - `zoo/routers/deck.py:12` → `deck.derive_wells_preview` / `deck.resolve_load_names` (drop the `_`-imports).
   - `zoo/routers/gantry.py:348-388` → `is_measurement_result` / `list_measurement_methods` (delete `_is_protocol_measurement_return` and the `inspect.getmembers` reflection).
   - `zoo/routers/gantry.py:242-245` → `session.calibration_active` (delete the `getattr` private-flag reads).
   - `zoo/routers/deck.py:185-219` → the labware type→schema mapping (delete `_normalize_well_plate_config`/`_normalize_vial_config` field lists).
   - `zoo/routers/gantry.py:280-290` → the structured error attribute/subtypes (delete the message-fragment matching).
   - `zoo/routers/gantry.py:309-334` → `instruments.registry.config_fields` (delete signature reflection + hardcoded `pipette_model` choices).
4. **Update Zoo tests** for the changed seams; add one test per switched seam asserting the public API is used (e.g. monkeypatch the public function and assert the route calls it).

## Gate

`cd /Users/alexchan/Documents/Ursa/Zoo && .venv/bin/python -m pytest tests/ -q` fully green (baseline was 191 backend tests / 95% coverage after the 2026-07-05 Zoo audit); `cd frontend && npm run build` clean if any frontend types changed (they shouldn't). Report any API-shape mismatch you hit against CubOS task 09's exports instead of working around it — the CubOS side should be fixed first.
