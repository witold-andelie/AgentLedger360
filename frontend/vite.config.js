import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: `npm run dev` on :5173, FastAPI on :8000 (uvicorn agentledger.server:create_app --factory --port 8000).
// Prod: `npm run build` -> dist/, served by FastAPI at "/" (same origin, no CORS needed).
// 127.0.0.1, not localhost: on Windows localhost is often ::1, and the API listens on IPv4 only.
const backend = { target: 'http://127.0.0.1:8000', changeOrigin: true, secure: false }

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': backend,
      '/platform': backend,
      '/sellers': backend,
    },
  },
})
