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
npm run build
```

Vite writes production assets to `dist/`. The API service and appliance image
serve those compiled files; customer devices do not run Node.js at startup.
