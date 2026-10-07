"""Import burst cadence from the game packages for every fire mode.

A behaviour with ``state:WeaponBurstStateBehavior`` fires NumShots rounds per
trigger pull, BurstDelay seconds apart (all at once when 0: Quartakk's four
barrels); the exported fireRate counts pulls. The export keeps neither field,
so a burst mode used to fire one round per pull (Hind, Quartakk). Modes are
matched by the behaviour position the export records as ``fireModes[i].index``,
so an Incarnon form that is its own behaviour (Sybaris: 2-round base, 4-round
form) carries its own burst and an automatic form (Burston) none.
IgnoreFireRate = 1 keeps BurstDelay unscaled by fire-rate mods;
BurstRemainingClip = 1 makes one pull fire the whole remaining magazine
(Cyanex 11, Nagantaka 9 rounds) instead of NumShots.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import load


def burst_states(native):
    for position, behaviour in enumerate(native.get('Behaviors') or []):
        if isinstance(behaviour, dict) and isinstance(behaviour.get('state:WeaponBurstStateBehavior'), dict):
            yield position, behaviour['state:WeaponBurstStateBehavior']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True, help='raw build dir with Packages.bin and packages/')
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/burst-profiles.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    out, skipped = {}, {}
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        native = pkg.resolve(row['path']) or {}
        modes = row.get('fireModes') or []
        entry = {}
        for position, state in burst_states(native):
            shots = state.get('NumShots')
            delay = state.get('BurstDelay')
            matches = [i for i, mode in enumerate(modes) if mode.get('index', i) == position]
            if not isinstance(shots, int) or shots < 2 or delay is None or len(matches) != 1:
                skipped.setdefault(row['path'], []).append(dict(name=row.get('nameEn'), behaviour=position, numShots=shots,
                                                                burstDelay=delay, modes=matches))
                continue
            mode = modes[matches[0]]
            entry[str(matches[0])] = dict(count=shots, delay_seconds=float(delay), ignoreFireRate=bool(state.get('IgnoreFireRate')),
                                          consumeAmmoOncePerBurst=bool(state.get('ConsumeAmmoOncePerBurst')),
                                          remainingClip=bool(state.get('BurstRemainingClip')), behaviour=position,
                                          trigger=mode.get('trigger'), fireRate=mode.get('fireRate'),
                                          isIncarnonForm=mode.get('isIncarnonForm'))
        if entry:
            record = dict(name=row.get('nameEn'), modes=entry)
            own = pkg._path_to_file(row['path'])
            if own.is_file():
                record['nativeSha256'] = hashlib.sha256(own.read_bytes()).hexdigest()
            out[row['path']] = record
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_burst_profiles.py',
                   semantics='per fire mode: count rounds per pull, delay_seconds apart (scaled by fire-rate mods unless '
                             'ignoreFireRate), then 1 / fireRate to the next pull; remainingClip: count = rounds left',
                   weapons=out, skipped=skipped)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(len(out), 'weapons with burst modes;', len(skipped), 'skipped')
    for record in out.values():
        print(f"  {record['name']:20s} " + '  '.join(f"mode {k}: {'clip' if m['remainingClip'] else m['count']} x {m['delay_seconds']:g}s @ {m['fireRate']}"
                                                   + (' (incarnon)' if m['isIncarnonForm'] else '') for k, m in record['modes'].items()))
    for path, rows in skipped.items():
        print('  skipped', rows)


if __name__ == '__main__':
    main()
