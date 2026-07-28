# CubOS Operator Web

The operator web application is the browser client for the `cubos_api` FastAPI
service. It uses the same `/api/v1` contract as the Python SDK and contains no
independent CubOS runtime or hardware implementation.

From this directory:

```bash
npm ci
npm run dev
npm run lint
npm run test -- --run
npm run test:e2e
npm run build
```

`npm run test:e2e` runs the Playwright suite in `tests/e2e/` against a
Vite dev server it starts itself; every `/api/v1` call is mocked in the
tests, so no CubOS backend or hardware is needed. If Playwright's own
browser download is unavailable, point it at a system Chromium with
`PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome npm run test:e2e`.

Vite writes production assets to `dist/`. The API service and appliance image
serve those compiled files; customer devices do not run Node.js at startup.
