import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const DEV_PORT = 5173
const API_TARGET = 'http://127.0.0.1:8742'

// The CubOS API's CSRF guard rejects state-changing requests whose
// Origin isn't the API's own host:port; `changeOrigin` rewrites Host but
// not Origin/Referer, so without rewriting these too every
// POST/PUT/DELETE from `npm run dev` gets a 403 "Cross-origin request
// blocked". Only the dev server's own origin is rewritten — a request
// whose Origin matches the loopback Host it arrived on — so the backend
// still blocks genuinely cross-origin callers. Matching against the
// request's Host (not DEV_PORT) keeps this working when vite is started
// with a `--port` override or falls back to another port.
const DEV_HOSTNAMES = new Set(['localhost', '127.0.0.1', '[::1]'])
const isDevServerOrigin = (origin?: string, host?: string): boolean => {
  if (!origin || !host || origin !== `http://${host}`) return false
  try {
    return DEV_HOSTNAMES.has(new URL(origin).hostname)
  } catch {
    return false
  }
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: DEV_PORT,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            if (isDevServerOrigin(req.headers.origin, req.headers.host)) {
              proxyReq.setHeader('origin', API_TARGET)
              proxyReq.removeHeader('referer')
            }
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // Playwright owns tests/e2e (run via `npm run test:e2e`); vitest must
    // not pick those specs up.
    exclude: [...configDefaults.exclude, 'tests/e2e/**'],
  },
})
