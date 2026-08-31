import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

const root = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  root,
  test: {
    environment: 'node',
    include: ['physical-world-v1.test.js', 'living-room-sofa-v1.test.js', 'living-room-furniture-v1.test.js', 'living-room-media-v1.test.js', 'floor-coverage-v1.test.js', 'bedroom-window-wall-v1.test.js', 'burgener-desk-v1.test.js', 'workstation-accessories-v1.test.js', 'bedroom-stable-decor-v1.test.js'],
  },
})
