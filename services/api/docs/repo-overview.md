# CubOS API and client overview

The monorepo contains one runtime, one HTTP service, and clients including an
optional SiLA 2 adapter:

```text
apps/operator-web/  ----\
                          >---- /api/v1 ---- services/api/ ---- packages/core/
sdk/python/         ----/
services/sila/      ----/  <- external SiLA 2 clients
```

`packages/core/` owns CubOS validation, deck geometry, movement, protocols,
instruments, calibration primitives, and data storage. `services/api/` exposes
those capabilities through `cubos_api`. The operator web and Python SDK are
clients of that same API and do not implement a second runtime.
The optional [SiLA server](../../../docs/sila.md) delegates protocol presets,
progress, cancellation requests, and artifact retrieval to that API as well.

## Key directories

| Path | Purpose |
| --- | --- |
| `packages/core/src/cubos/` | Runtime package |
| `services/api/src/cubos_api/` | FastAPI service |
| `apps/operator-web/src/` | React operator client |
| `sdk/python/src/cubos_client/` | Python SDK and sender CLI |
| `services/sila/src/cubos_sila/` | SiLA 2 appliance server |
| `deploy/docker/` | Raspberry Pi appliance image |
| `deploy/windows/` | Windows operator installer |

## Entrypoints

```bash
python -m cubos_api
cd apps/operator-web && npm run dev
cubos-send --help
```

All HTTP resources are rooted at `/api/v1`. Discovery and health endpoints are
hardware-safe. Motion and protocol endpoints delegate to the process-local
CubOS `GantrySession`, which remains the sole hardware owner.

## Development checks

```bash
python -m pytest packages/core/tests -q
python -m pytest services/api/tests -q
python -m pytest sdk/python/tests -q
cd apps/operator-web && npm run lint && npm run test -- --run && npm run build
```

Do not connect, home, jog, calibrate, or run a protocol during automated
validation. Those actions require an operator-led hardware test with normal lab
safety controls.
