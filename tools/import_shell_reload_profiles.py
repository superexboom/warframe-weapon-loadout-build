"""Import round-by-round (shell) reload timings from the game packages.

A state behaviour with AmmoTakenPerReload = 1 loads one round per loop:
reloadStartTime, then reloadLoopTime per round, then reloadEndTime. The
exported ReloadTime is not that total (Strun: 1 s exported, 0.5 + 0.5 x 6 +
0.25 = 3.75 s native, the wiki / WFSim figure). ReloadDuringModeSwitch says a
form switch loads owed rounds (Felarx). Only the first such behaviour (the
base form) is taken; Incarnon forms use their own charge pool.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import load


def shell_state(native):
    for behaviour in native.get('Behaviors') or []:
        if not isinstance(behaviour, dict):
            continue
        for key, state in behaviour.items():
            if key.startswith('state:') and isinstance(state, dict) and state.get('AmmoTakenPerReload') == 1:
                return key.split(':', 1)[1], state
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True, help='raw build dir with Packages.bin and packages/')
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/shell-reload-profiles.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    out, skipped = {}, {}
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        native = pkg.resolve(row['path']) or {}
        behaviour, state = shell_state(native)
        if not state:
            continue
        times = [state.get(k) for k in ('reloadStartTime', 'reloadLoopTime', 'reloadEndTime')]
        if any(v is None for v in times):
            skipped[row['path']] = dict(name=row.get('nameEn'), behaviour=behaviour, missing=[k for k, v in
                                        zip(('reloadStartTime', 'reloadLoopTime', 'reloadEndTime'), times) if v is None])
            continue
        entry = dict(name=row.get('nameEn'), behaviour=behaviour, reloadStart=float(times[0]), reloadPerShell=float(times[1]),
                     reloadEnd=float(times[2]), modeSwitchLoadsShell=bool(state.get('ReloadDuringModeSwitch')),
                     exportMagazine=row.get('magazineSize'), exportReloadTimes=[m.get('reloadTime') for m in row.get('fireModes') or []])
        own = pkg._path_to_file(row['path'])
        if own.is_file():
            entry['nativeSha256'] = hashlib.sha256(own.read_bytes()).hexdigest()
        out[row['path']] = entry
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_shell_reload_profiles.py',
                   semantics='full reload of n rounds = reloadStart + reloadPerShell * n + reloadEnd, all / reload speed',
                   weapons=out, skipped=skipped)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(len(out), 'round-by-round reloads;', len(skipped), 'skipped')
    for e in out.values():
        mag = e['exportMagazine'] or 6
        print(f"  {e['name']:16s} {e['reloadStart']:g} + {e['reloadPerShell']:g} x {mag:g} + {e['reloadEnd']:g}"
              f" = {e['reloadStart'] + e['reloadPerShell'] * mag + e['reloadEnd']:.3g} s (export {e['exportReloadTimes']})")


if __name__ == '__main__':
    main()
