"""Import kill-charged alternate fires (Trumna grenade, Sepulcrum, Higasa, Morgha, Mausolon).

The weapon's charge system (the one Incarnon gauges use) is native:
``AddChargeConditions`` says what earns charges, ``NumChargesToAdd`` how many
(default 1), ``ConsumeChargeConditions`` SECONDARY_FIRE that the alternate
fire spends ``NumChargesToConsume`` per shot (``RequireFullCharges`` /
``MaxCharges``: Higasa needs its full 100 at 7 per kill). For the kill
conditions (PRIMARY_KILL, DEFAULT_BEHAVIOR_KILL) the alternate fire cannot be
fired on its own: it fires once per ``killsPerUse`` primary kills. The
replay runs it as a cycle (primary until the gauge is full, switch with the
alternate behaviour's ``ModeSwitchTime`` - 1 s on Trumna, 0 elsewhere -
fire, switch back with the primary's). Modes are matched by behaviour
position (export ``fireModes[i].index``).
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import load
from wfarsenal.extract import _sub_behaviour

KILL_CONDITIONS = {'PRIMARY_KILL', 'DEFAULT_BEHAVIOR_KILL'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True)
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/kill-charge-profiles.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    out, skipped = {}, []
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        native = pkg.resolve(row['path']) or {}
        add_on = set(native.get('AddChargeConditions') or [])
        if not add_on & KILL_CONDITIONS or 'SECONDARY_FIRE' not in (native.get('ConsumeChargeConditions') or []):
            continue
        consume = float(native.get('NumChargesToConsume') or 0)
        add = float(native.get('NumChargesToAdd') or 1)
        if consume <= 0:
            skipped.append(dict(name=row['nameEn'], reason='NumChargesToConsume 0: charges scale the shot, not gate it'))
            continue
        behaviours = native.get('Behaviors') or []
        alt = [i for i, b in enumerate(behaviours) if isinstance(b, dict)
               and (_sub_behaviour(b, 'fire:') or {}).get('ConsumesChargesForFire')]
        modes = row.get('fireModes') or []
        if len(alt) != 1:
            skipped.append(dict(name=row['nameEn'], reason=f'{len(alt)} charge-consuming behaviours'))
            continue
        alt_modes = [i for i, m in enumerate(modes) if m.get('index', i) == alt[0]]
        primary_modes = [i for i, m in enumerate(modes) if m.get('index', i) == 0]
        if len(alt_modes) != 1 or primary_modes != [0]:
            skipped.append(dict(name=row['nameEn'], reason='alternate / primary mode not matched'))
            continue
        alt_state = _sub_behaviour(behaviours[alt[0]], 'state:') or {}
        primary_state = _sub_behaviour(behaviours[0], 'state:') or {}
        max_charges = float(native.get('MaxCharges') or consume)
        kills = math.ceil(consume / add - 1e-9)
        entry = dict(name=row['nameEn'], altMode=alt_modes[0], primaryMode=0, killsPerUse=kills,
                     shotsPerGauge=max(1, int(max_charges // consume)) if not native.get('RequireFullCharges') else 1,
                     switchInSeconds=float(alt_state.get('ModeSwitchTime') or 0.),
                     switchOutSeconds=float(primary_state.get('ModeSwitchTime') or 0.),
                     native=dict(AddChargeConditions=sorted(add_on), NumChargesToAdd=add, NumChargesToConsume=consume,
                                 MaxCharges=native.get('MaxCharges'), RequireFullCharges=native.get('RequireFullCharges')))
        own = pkg._path_to_file(row['path'])
        if own.is_file():
            entry['nativeSha256'] = hashlib.sha256(own.read_bytes()).hexdigest()
        out[row['path']] = entry
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_kill_charged_alts.py',
                   semantics='the alternate mode fires shotsPerGauge shots per killsPerUse primary-fire kills; selecting it '
                             'replays the primary + alternate cycle',
                   weapons=out, skipped=skipped)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(len(out), 'kill-charged alternates;', len(skipped), 'skipped')
    for e in out.values():
        print(f"  {e['name']:14s} mode {e['altMode']}: {e['killsPerUse']} kills -> {e['shotsPerGauge']} shot, switch {e['switchInSeconds']:g}/{e['switchOutSeconds']:g}s")
    for s in skipped:
        print('  skip', s)


if __name__ == '__main__':
    main()
