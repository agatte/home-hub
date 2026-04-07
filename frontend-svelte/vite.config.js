import { sveltekit } from '@sveltejs/kit/vite'
import { defineConfig } from 'vite'

// Dev server runs on 3001 so the existing React dev server (port 3000)
// keeps working during the parity port. Proxy block matches
// frontend/vite.config.js so backend URLs stay relative in source.
export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 3001,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/health': 'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
})
