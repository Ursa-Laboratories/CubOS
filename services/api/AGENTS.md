# CubOS API Agent Guide

The `cubos_api` service is the single HTTP boundary over the CubOS runtime.
Both the operator web application and the Python SDK consume its versioned
`/api/v1` contract.

## Retrieval-led workflow

Read `docs/agent-index.md` before changing routes, CubOS integration, operator
web behavior, coordinate handling, tests, or deployment behavior. Prefer the
repository's source and documentation over remembered behavior.

## Core rules

- Keep routers thin. Validation, deck math, protocol execution, movement, and
  instrument behavior belong in `packages/core/src/cubos/`.
- Import the installed `cubos` package; never reach across the monorepo with
  `sys.path` or `PYTHONPATH` hacks.
- API models describe HTTP payloads and must not become a second source of
  truth for CubOS schemas.
- The operator web and SDK must use the same `/api/v1` resources.
- Do not execute motion or protocols during automated validation.

## Key paths

- `src/cubos_api/app.py`
- `src/cubos_api/config.py`
- `src/cubos_api/routers/`
- `src/cubos_api/services/`
- `../../apps/operator-web/src/api/`
- `../../sdk/python/src/cubos_client/`
- `tests/`

## Commands

Run these from the monorepo root:

```bash
python -m pytest services/api/tests -q
cd apps/operator-web && npm run lint && npm run test -- --run && npm run build
python -m cubos_api
```

## Coordinate and calibration semantics

CubOS uses a front-left-bottom deck origin: +X right, +Y back, +Z up. Clients
must not negate X or Y. `working_volume` is the usable deck/WPos range; GRBL
`max_travel_*` includes the configured homing pull-off reserve. Calibration UI
and API code may sequence operator actions, but controller behavior remains in
the CubOS runtime.

## Local state

- Default API config seeds: `services/api/configs/`
- Persistent device state: `~/.cubos/` unless deployment settings override it
- Settings endpoint: `/api/v1/settings`
- Operator web build: `apps/operator-web/dist/`

Keep `README.md`, `docs/repo-overview.md`, and the root deployment documentation
current when these contracts change.
