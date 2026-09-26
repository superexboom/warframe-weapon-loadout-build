// Run the exact WASM shipped with a pinned WFSim checkout; no server needed.
// Usage: node tools/run_reference_wasm.mjs REPO ENDPOINT INPUT.json OUTPUT.json
import fs from 'node:fs';
import path from 'node:path';
const args = process.argv.slice(2);
if (args.length !== 4) {
  console.error('Usage: node tools/run_reference_wasm.mjs REPO ENDPOINT INPUT.json OUTPUT.json');
  process.exit(2);
}
const [repo, endpoint, input, output] = args;
if (!endpoint.startsWith('/api/')) throw new Error('Expected an /api/ endpoint');
if (fs.existsSync(output)) throw new Error('Output exists; preserve the previous experiment');
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/, ''));
const release = readJson(path.join(repo, 'site/release.json'));
if (!/^[a-f0-9]+$/.test(release.wasm)) throw new Error('Invalid WASM release identifier');
const base = path.join(repo, 'site/pkg');
const source = fs.readFileSync(path.join(base, `wfsim_wasm.${release.wasm}.js`), 'utf8');
const engine = new Function(source + ';return wasm_bindgen;')();
engine.initSync({ module: fs.readFileSync(path.join(base, `wfsim_wasm_bg.${release.wasm}.wasm`)) });
const result = JSON.parse(engine.api(endpoint, JSON.stringify(readJson(input))));
fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
fs.writeFileSync(output, JSON.stringify(result, null, 2) + String.fromCharCode(10), { flag: 'wx' });
if (result.ok === false) {
  console.error('Reference rejected the request; inspect the saved response');
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({ output: path.resolve(output), release, runs: result.runs, duration: result.duration, score: result.score, kpm: result.duration ? 60 * result.score / result.duration : null }));
}
