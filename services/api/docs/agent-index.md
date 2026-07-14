# CubOS API retrieval index

Read `../AGENTS.md` and this file before changing the API or either client.
`cubos_api` is a thin HTTP layer over the installed `cubos` runtime package.

## API boundary

- `../src/cubos_api/app.py` — app factory, middleware, static operator web.
- `../src/cubos_api/config.py` — `CUBOS_*` settings and local state paths.
- `../src/cubos_api/routers/` — versioned `/api/v1` routes.
- `../src/cubos_api/services/` — YAML I/O and durable run orchestration.
- `../tests/` — backend contract and safety expectations.

Routers may translate HTTP payloads and coordinate service lifecycles. CubOS
runtime validation, movement, deck resolution, protocols, instruments, and
calibration behavior stay in `../../../packages/core/src/cubos/`.

## Client boundary

- `../../../apps/operator-web/src/api/client.ts` — browser API client.
- `../../../apps/operator-web/src/types/` — HTTP payload shapes.
- `../../../apps/operator-web/src/hooks/` — TanStack Query hooks.
- `../../../apps/operator-web/src/components/` — operator UI.
- `../../../sdk/python/src/cubos_client/` — Python SDK and sender CLI.

Both clients consume the same `/api/v1` API. Neither client owns hardware or
duplicates CubOS schemas.

## Coordinate rule

Display and submit CubOS deck coordinates directly: front-left-bottom origin,
+X right, +Y back, +Z up. Do not add client-side axis sign changes. Changes to
motion or calibration behavior belong in the core runtime and require separate
physical validation.

## Verification

From the monorepo root:

```bash
python -m pytest services/api/tests -q
python -m pytest sdk/python/tests -q
cd apps/operator-web
npm run lint
npm run test -- --run
npm run build
```

These gates must not connect, home, jog, calibrate, or run a real protocol.
