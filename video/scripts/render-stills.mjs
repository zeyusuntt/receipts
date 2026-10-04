import {readFileSync, mkdirSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
const timeline = JSON.parse(readFileSync('src/content/timeline.json', 'utf8'));
mkdirSync('out/stills', {recursive: true});
for (const beat of timeline.beats) {
  const frame = Math.round((beat.start_s + beat.end_s) / 2 * timeline.fps);
  const result = spawnSync('npx', ['--no-install', 'remotion', 'still', 'src/index.ts', 'Receipts', `out/stills/${beat.id}.png`, `--frame=${frame}`], {stdio: 'inherit'});
  if (result.status !== 0) process.exit(result.status ?? 1);
}
const diagram = spawnSync('npx', ['--no-install', 'remotion', 'still', 'src/index.ts', 'ArchitectureMap', 'out/stills/architecture.png', '--frame=0'], {stdio: 'inherit'});
process.exit(diagram.status ?? 1);
