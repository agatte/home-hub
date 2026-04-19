/**
 * Renders all background compositions to MP4 files.
 * Output goes to ../frontend-svelte/static/backgrounds/
 *
 * Usage: node scripts/render-all.mjs
 */

import { execSync } from "child_process";
import { existsSync, mkdirSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = resolve(__dirname, "../../frontend-svelte/static/backgrounds");

// Add composition IDs here as you create them
const COMPOSITIONS = [
  "GamingBackground",
  // "WorkingBackground",
  // "RelaxBackground",
  // "SleepingBackground",
  // "IdleBackground",
  // "SocialBackground",
  // "WatchingBackground",
  // "MovieBackground",
];

if (!existsSync(OUTPUT_DIR)) {
  mkdirSync(OUTPUT_DIR, { recursive: true });
}

for (const comp of COMPOSITIONS) {
  const filename = comp.replace("Background", "").toLowerCase();
  const output = resolve(OUTPUT_DIR, `${filename}-bg.mp4`);

  console.log(`\nRendering ${comp} → ${output}`);

  try {
    execSync(
      `npx remotion render src/index.ts ${comp} ${output} --codec=h264`,
      { stdio: "inherit", cwd: resolve(__dirname, "..") }
    );
    console.log(`  Done: ${output}`);
  } catch (err) {
    console.error(`  Failed to render ${comp}:`, err.message);
    process.exit(1);
  }
}

console.log("\nAll backgrounds rendered.");
