import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const toolDirectory = path.dirname(fileURLToPath(import.meta.url))
const frontendDirectory = path.resolve(toolDirectory, '..', '..')
const repositoryDirectory = path.resolve(frontendDirectory, '..')
const output = path.join(toolDirectory, 'generated', 'geometry-scene.json')
const python = process.platform === 'win32' ? 'python' : 'python3'

const result = spawnSync(
  python,
  ['scripts/compile_apartment_canvas_geometry_scene.py', '--output', output, '--summary'],
  { cwd: repositoryDirectory, encoding: 'utf8', stdio: 'inherit' },
)

if (result.status !== 0) {
  process.exit(result.status ?? 1)
}
