import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173, strictPort: true,
    proxy: { '/v1': { target: process.env.BACKEND_URL || 'http://localhost:8088', changeOrigin: false } },
  },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], restoreMocks: true },
})
