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
  build: {
    // Threlte + Three.js produces a ~700kB chunk on the index route (moon
    // scene). Lazy-splitting it is a separate task; bump the warning floor
    // until then so the build output stays clean.
    chunkSizeWarningLimit: 800,
  },
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
