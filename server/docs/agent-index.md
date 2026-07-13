# Zoo Agent Index

Use this as the first retrieval map for coding agents. Prefer repo source/docs over model memory, especially for CubOS integration, config validation, coordinate display, and frontend/backend boundaries.

## Start here

- Always read `AGENTS.md`, `CLAUDE.md`, and this file before coding.
- Zoo is a thin UI/API layer over CubOS. Do not recreate CubOS validation, protocol execution, movement, deck resolution, or hardware logic.
- If behavior changes, update `README.md`, `docs/repo-overview.md`, and progress notes under `progress/`.

## Architecture boundary

Read these before changing backend routes, config handling, or CubOS integration:

- `AGENTS.md` and `CLAUDE.md` — core rules and documentation contract.
- `zoo/app.py`, `zoo/__main__.py`, `zoo/config.py` — app setup and runtime settings.
- `zoo/routers/` — FastAPI endpoints; keep these thin.
- `zoo/services/yaml_io.py` — YAML read/write helper.
- `tests/` — backend behavior expectations.

Rule: write YAML from UI/API input, then read it back through CubOS loaders/schemas. CubOS remains the source of truth.

## CubOS API usage

Use CubOS public modules/classes instead of duplicating behavior:

- Deck/config validation: `load_deck_from_yaml`, CubOS deck schemas/loaders.
- Gantry/instrument validation: CubOS gantry schema and instrument registry. `/api/gantry/instrument-schemas` stays a thin reflection of CubOS and returns fields nested by `type` then `vendor`.
- Movement: CubOS `Gantry` and public protocol/movement methods.
- Calibration: keep Zoo UI/API orchestration thin over CubOS `Gantry` methods and the canonical serial flow in `CubOS/setup/calibrate_gantry.py`, including blocking home/center/retract operations and temporary XY-origin soft-limit disabling.
- Protocols: CubOS protocol loaders/runtime APIs using gantry, deck, and protocol configs.

Never send raw serial/GRBL from Zoo and never prepend local CubOS source paths onto `sys.path`.

## Frontend routing map

Read these before changing the React UI:

- `frontend/src/api/client.ts` — API client functions.
- `frontend/src/theme.ts` — design tokens and shared style objects; all component styling pulls from here (no hardcoded hex in components). Interaction states (hover/focus/disabled) live in `frontend/src/index.css`.
- `frontend/src/types/index.ts` — API payload types; keep them response/input shapes, not duplicated CubOS schema truth.
- `frontend/src/hooks/` — TanStack Query hooks.
- `frontend/src/components/` — UI components; gantry jog/readout and calibration UI live under `frontend/src/components/gantry/`.
- `frontend/src/utils/coordinates.ts` — coordinate/display helpers.
- `frontend/src/*.test.tsx`, `frontend/src/**/*.test.tsx` — frontend behavior tests.

## Coordinate display rule

CubOS/backend coordinates and hardware semantics are not redefined in Zoo. Zoo displays CubOS coordinates directly in the deck-origin frame. Before changing coordinate display, read:

- `AGENTS.md` coordinate convention section.
- `frontend/src/utils/coordinates.ts` and tests.
- Relevant gantry route/component tests.

## Verification gates

Use the smallest meaningful gate first, then broaden as risk requires:

```bash
pytest tests/
cd frontend && npm run lint
cd frontend && npm run test
cd frontend && npm run build
```

For docs-only changes, direct inspection and grep are acceptable, but PRs should still say no runtime behavior changed.

## Common gotchas

- Do not duplicate CubOS Pydantic schemas in Zoo models.
- Do not move validation/business logic from CubOS into Zoo routers.
- Keep local config directory behavior explicit (`configs/` by default, settings API can redirect it).
- If a change affects hardware-touching routes, say what can move and what physical validation remains.
