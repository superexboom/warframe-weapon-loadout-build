"""Import fire modes that reload after every shot (spear-gun throws).

``state:LotusSpearGunStateBehavior`` with ``ReloadAfterEveryShot = 1``
(Scourge, Scourge Prime, Javlok, Ferrox, Tenet Ferrox throws). Static
analysis of Warframe.x64.exe (CN build, 2026-09-25): the class's post-shot
virtual (vtable 0x142361300 slot 45) checks ReloadAfterEveryShot (+0x1a4) and
DestroyActiveProjectiles (+0x1a5), switches the weapon to state 8 and plays
event 0x79 for the duration returned by the weapon's virtual +0x2d0 - the
same state / event / duration the generic reload path (0x1405ac670) uses. So
each throw is followed by an ordinary reload of the weapon's (modded) reload
time, whatever the throw's ammo cost. Modes are matched by behaviour position.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import load
from wfarsenal.extract import _sub_behaviour


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True)
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/reload-after-shot.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    out = {}
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        native = pkg.resolve(row['path']) or {}
        modes = row.get('fireModes') or []
        entry = {}
        for position, behaviour in enumerate(native.get('Behaviors') or []):
            state = _sub_behaviour(behaviour, 'state:') if isinstance(behaviour, dict) else None
            if not state or not state.get('ReloadAfterEveryShot'):
                continue
            matches = [i for i, m in enumerate(modes) if m.get('index', i) == position]
            if len(matches) == 1:
                mode = modes[matches[0]]
                entry[str(matches[0])] = dict(behaviour=position, stateType=next((v for k, v in behaviour.items() if k == 'state:Type'), None),
                                              reloadTime=state.get('reloadTime'), trigger=mode.get('trigger'), fireRate=mode.get('fireRate'))
        if entry:
            own = pkg._path_to_file(row['path'])
            out[row['path']] = dict(name=row['nameEn'], modes=entry,
                                    **({'nativeSha256': hashlib.sha256(own.read_bytes()).hexdigest()} if own.is_file() else {}))
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_reload_after_shot.py',
                   semantics='after every shot of the mode the weapon reloads (ordinary reload time and reload-speed mods)',
                   evidence='Warframe.x64.exe LotusSpearGunStateBehavior vtable slot 45 -> state 8 / event 0x79 / weapon+0x2d0, as the generic reload path',
                   weapons=out)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(len(out), 'weapons');[print(' ', r['name'], {k: (m['reloadTime'], m['trigger']) for k, m in r['modes'].items()}) for r in out.values()]


if __name__ == '__main__':
    main()
