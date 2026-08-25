import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.API_PROXY_TARGET ?? 'http://host.docker.internal:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    allowedHosts: ['frontend-dev'],
    port: 5173,
    strictPort: true,
    watch: {
      usePolling: process.env.VITE_USE_POLLING === 'true',
      ignored: ['**/playwright-report/**', '**/test-results/**'],
    },
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: false,
        headers: { Host: 'localhost' },
        timeout: 0,
        proxyTimeout: 0,
      },
      '/health': {
        target: apiTarget,
        changeOrigin: false,
        headers: { Host: 'localhost' },
      },
    },
  },
})
