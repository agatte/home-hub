import { sveltekit } from '@sveltejs/kit/vite'
import { defineConfig } from 'vite'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig({
  plugins: [
    sveltekit(),
    ...(process.env.ANALYZE ? [visualizer({
      open: false,
      filename: 'stats.html',
      gzipSize: true,
      brotliSize: true,
    })] : []),
  ],
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
