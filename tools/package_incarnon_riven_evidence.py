"""Archive completed Incarnon/Riven verification with its model identity."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a new evidence directory')
    import app
    fingerprint = app._analysis_inputs_fingerprint()
    acceptance = ROOT / '.local/reports/incarnon-riven-sync-20261001/final-searches'
    files = sorted(acceptance.glob('[0-9][0-9]-*.json'))
    if len(files) != 6:
        raise ValueError('all six completed searches are required')
    for path in files:
        record = json.loads(path.read_text(encoding='utf-8'))
        if not record.get('passed') or record.get('fingerprint') != fingerprint:
            raise ValueError('search failure or model drift: ' + path.name)
    sources = {f'searches/{p.name}': p for p in files}
    sources['searches/summary.json'] = acceptance / 'summary.json'
    for name in ('browser-verification.json', 'incarnon-desktop-final.png'):
        sources[name] = ROOT / '.local/reports/incarnon-riven-sync-20261001' / name
    sources['native-descriptions.json'] = ROOT / '.local/reports/incarnon-riven-sync-20260930/native-descriptions.json'
    sources['incarnon-mobile.png'] = ROOT / '.local/reports/incarnon-riven-sync-20260930/incarnon-mobile-focus.png'
    args.output.mkdir(parents=True)
    entries = []
    for relative, source in sources.items():
        target = args.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entries.append(dict(path=relative, source=source.relative_to(ROOT).as_posix(),
                            size=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    manifest = dict(createdAt=datetime.now(timezone.utc).isoformat(),
                    sourceCommit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    fingerprint=fingerprint, cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION,
                    scope='Six constrained searches, 18 recommendation and 18 analysis replays, plus browser checks. Full-roster bake remains separate.',
                    files=entries)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('hashed evidence files:', len(entries))


if __name__ == '__main__':
    main()
