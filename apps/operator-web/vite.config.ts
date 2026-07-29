import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const DEV_PORT = 5173
const API_TARGET = 'http://127.0.0.1:8742'

// Origins the dev server itself may be reached on. The CubOS API's CSRF
// guard rejects state-changing requests whose Origin isn't the API's own
// host:port; `changeOrigin` rewrites Host but not Origin/Referer, so
// without rewriting these too every POST/PUT/DELETE from `npm run dev`
// gets a 403 "Cross-origin request blocked". Only the dev server's own
// origin is rewritten — anything else stays untouched so the backend
// still blocks genuinely cross-origin callers.
const DEV_ORIGINS = new Set(
  ['localhost', '127.0.0.1', '[::1]'].map((host) => `http://${host}:${DEV_PORT}`),
)

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
            if (DEV_ORIGINS.has(req.headers.origin ?? '')) {
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
