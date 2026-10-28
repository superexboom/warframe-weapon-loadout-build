"""Stage runtime source identity and a matching baked cache for PyInstaller."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _metadata(destination: Path) -> dict:
    code = """import json,sys
sys.path.insert(0,sys.argv[1]);sys.frozen=True;sys._MEIPASS=sys.argv[1]
import app
print(json.dumps(dict(inputs=app._analysis_inputs_fingerprint(),buildLabel=app.EXPORTS['buildLabel'],
                     stances=app._stances_fingerprint(),cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION)))
"""
    env = dict(os.environ, WF_RIVEN_ROOT=str(destination), WF_ANALYZER_SERIAL='1',
               WF_ANALYSIS_STATICS_CACHE_PATH=str(destination / '.probe-cache.json'))
    result = subprocess.run([sys.executable, '-I', '-c', code, str(destination)], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=90)
    if result.returncode:
        raise RuntimeError('staged runtime identity failed:\n' + result.stderr[-6000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def stage(root: Path, destination: Path, *, require_cache: bool = False) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if root == destination or not (destination / 'data/source-lock.json').is_file():
        raise ValueError('destination must be a separately staged runtime with data/source-lock.json')
    # The data bundler may pretty-print the unchanged source lock. Identity
    # hashes its bytes, so preserve the source bytes only after semantic equality
    # is proven. A different snapshot/lock must retain its own identity.
    original_lock = root / 'data/source-lock.json'
    staged_lock = destination / 'data/source-lock.json'
    if json.loads(original_lock.read_bytes()) == json.loads(staged_lock.read_bytes()):
        staged_lock.write_bytes(original_lock.read_bytes())
    module_dir = destination / 'wfarsenal'
    module_dir.mkdir(parents=True, exist_ok=True)
    for source in (root / 'vendor/wfarsenal').glob('*.py'):
        shutil.copy2(source, module_dir / source.name)
    for name in ('app.py', 'data_sources.py', 'enemy_assets.py'):
        shutil.copy2(root / name, destination / name)
    metadata = _metadata(destination)
    source = root / '.local/cache/riven-analysis-statics.json'
    target = destination / 'data/riven-analysis-statics.json'
    try:
        raw = source.read_bytes()
        payload = json.loads(raw)
        matched = (isinstance(payload, dict) and all(payload.get(k) == v for k, v in metadata.items())
                   and isinstance(payload.get('entries'), dict) and bool(payload['entries']))
    except (OSError, ValueError):
        matched = False
    if matched:
        target.write_bytes(raw)
        metadata.update(cacheEntries=len(payload['entries']), cacheSha256=hashlib.sha256(raw).hexdigest())
    else:
        if target.is_file():
            target.unlink()
        metadata['cacheEntries'] = 0
        if require_cache:
            raise ValueError('a nonempty baked cache matching the staged runtime is required')
    (destination / 'data/portable-runtime.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--require-cache', action='store_true')
    args = parser.parse_args()
    print(json.dumps(stage(args.root, args.destination, require_cache=args.require_cache), indent=2))


if __name__ == '__main__':
    main()
