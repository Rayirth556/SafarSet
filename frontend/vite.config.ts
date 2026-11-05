import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

const backend = process.env.SAFARSET_BACKEND ?? 'http://127.0.0.1:8000'

// The browser talks to one origin. `/sim` is also a page route, so only `/sim/<something>` (the demo-control API) is proxied.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    proxy: {
      '/api': backend,
      '/health': backend,
      '/docs': backend,
      '/openapi.json': backend,
      '^/sim/.+': backend,
      '/ws': { target: backend, ws: true },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
