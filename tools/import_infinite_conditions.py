"""List Incarnon conditional blocks whose buff never times out.

IsInfinite = 1 on the native source holds the buff until the condition's
ResetOnTags fire; its UpgradeDuration is then not a lifetime. The pinned
export does not carry the flag (vendor/wfarsenal/extract.py now writes
`isInfinite`), so the runtime reads this list: a listed source keeps its
stacks across reloads (the replay otherwise clears duration-less reload buffs
after the reload they started) and drops any UpgradeDuration.
Boar Reified Bane: PRE_RELOAD_FROM_EMPTY, reset PRE_RELOAD_FROM_NON_EMPTY,
IsInfinite 1, UpgradeDuration 1 (WFSim measured: held, never times out).
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import load


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True)
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/infinite-conditions.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    out = {}
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        for tier in (row.get('incarnon') or {}).get('tiers') or []:
            for branch in tier.get('branches') or []:
                for condition in branch.get('conditionalEffects') or []:
                    source = condition.get('sourcePath')
                    if not source or source in out:
                        continue
                    native = pkg.resolve(source) or {}
                    if not native.get('IsInfinite'):
                        continue
                    entry = dict(weapon=row.get('nameEn'), branch=branch.get('id'), exportDuration=condition.get('duration'),
                                 conditions=condition.get('conditions'))
                    own = pkg._path_to_file(source)
                    if own.is_file():
                        entry['nativeSha256'] = hashlib.sha256(own.read_bytes()).hexdigest()
                    out[source] = entry
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_infinite_conditions.py',
                   semantics='IsInfinite = 1: hold until the condition resets; ignore UpgradeDuration', sources=out)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    for source, e in out.items():
        print(f"  {e['weapon']:14s} {e['branch']} duration {e['exportDuration']} -> held  {source.rsplit('/', 1)[-1]}")


if __name__ == '__main__':
    main()
