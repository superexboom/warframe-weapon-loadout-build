"""Import native charge times for every non-melee charge mode.

The pinned export predates the extractor fix that reads the state
behaviour's ``ChargeTime`` (capital C), so every charge mode exports
``chargeTime: null`` and only hand-audited weapons (combat-reference
``auditedAttacks[...].charge``) charged before firing; Ferrox, Tenet Ferrox,
Javlok and the charged alt fires of Tenora / Battacor / Ambassador fired at
the bare pull rate. Modes are matched by the behaviour position the export
records as ``fireModes[i].index``.

``ChargeModifier`` names the upgrade that shortens the charge:
WEAPON_FIRE_RATE (fire-rate mods speed it up, the replay's default) or
WEAPON_CHARGE_RATE only (Phantasma). Audited entries keep their value; the
report lists any audited value that disagrees with the native one.

Perfect release (2026-10-07): a fire behaviour with ``PerfectChargeRange``
[low, high] and ``PerfectChargedProjectileType`` fires that projectile when
released between low and high of the charge (Nataruk 0.7-1.0, Cinta
0.7-0.9). It is recorded as ``perfect`` (ratio = low, the earliest perfect
release, and the projectile's damage resolved exactly as the export resolves
the mode's own projectile); the runtime uses it by default where it pays
(``paysOff``: unmodded expected damage per charge-plus-reload cycle not
below the full charge's; Nataruk yes, Cinta's 600 Heat shockwave no) unless
combatState.perfectCharge is false.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import load
from wfarsenal.extract import _resolve_damage, _sub_behaviour, _swapping_charge_routes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True, help='raw build dir with Packages.bin and packages/')
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--reference', type=Path, default=ROOT / 'data/mechanics/combat-reference.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/charge-profiles.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    audited = json.loads(a.reference.read_text(encoding='utf-8'))['auditedAttacks']
    out, disagreements = {}, []
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        if row.get('slot') in ('melee', 'arch_melee'):
            continue
        native = pkg.resolve(row['path']) or {}
        modes = row.get('fireModes') or []
        entry = {}
        bank=row.get('fireModeSource') or ('HeavyBehaviors' if row.get('slot')=='arch_gun' and native.get('HeavyBehaviors') else 'Behaviors')
        behaviours=native.get(bank) or []
        routes=_swapping_charge_routes(behaviours)
        for position, behaviour in enumerate(behaviours):
            if not isinstance(behaviour, dict):
                continue
            state = next((v for k, v in behaviour.items() if k.startswith('state:') and isinstance(v, dict)
                          and v.get('ChargeTime') is not None), None)
            route=routes.get(position)
            local_state=state
            if route:state=_sub_behaviour(behaviours[route['sourceBehavior']],'state:')
            seconds=route['seconds'] if route else float((state or {}).get('ChargeTime') or 0.)
            matches = [i for i, mode in enumerate(modes) if mode.get('index', i) == position]
            if not state or len(matches) != 1 or (seconds <= 0 and not route):
                continue
            index = matches[0]
            mode = modes[index]
            fire = _sub_behaviour(behaviour, 'fire:') or {}
            impact = _sub_behaviour(behaviour, 'impact:') or {}
            window = fire.get('PerfectChargeRange') or [0, 0]
            perfect = None
            if fire.get('PerfectChargedProjectileType') and 0 < float(window[0]) < 1:
                damage = _resolve_damage(pkg, row['path'], {**fire, 'projectileType': fire['PerfectChargedProjectileType']}, impact)
                if damage and damage.get('types'):
                    # Default only where it pays: unmodded expected damage per
                    # cycle (charge + the reload a bow pays between shots).
                    between = float(state.get('reloadTime') or 0.) if state.get('UseReloadTimeBetweenShots') else 0.
                    def rate(d, seconds):
                        hit = sum(d['types'].values()) * (1. + float(d.get('critChance') or 0.) * (float(d.get('critMultiplier') or 1.) - 1.))
                        return hit / max(seconds + between, 1e-9)
                    full = rate(mode['damage'], float(state['ChargeTime']))
                    fast = rate(damage, float(state['ChargeTime']) * float(window[0]))
                    perfect = dict(ratio=float(window[0]), window=[float(v) for v in window],
                                   projectile=damage.get('projectile') or fire['PerfectChargedProjectileType'], damage=damage,
                                   paysOff=fast >= full, unmoddedRate=dict(full=round(full, 3), perfect=round(fast, 3)),
                                   fullProjectile=mode['damage'].get('projectile'), fullTotal=sum(mode['damage']['types'].values()))
            entry[str(index)] = dict(seconds=seconds, chargeModifier=state.get('ChargeModifier'),
                                     minChargeRatio=state.get('MinChargeRatio'), autoFire=bool(state.get('AutoFireWhenChargeCompleted')),
                                     behaviour=position, trigger=mode.get('trigger'), fireRate=mode.get('fireRate'),
                                     exportChargeTime=mode.get('chargeTime'), **({'beforeFire':route['beforeFire'],'chargeSourceBehavior':route['sourceBehavior'], 'nativeLocalChargeTime':(local_state or {}).get('ChargeTime'),'sourceBehaviorBank':bank} if route else {}), **({'perfect': perfect} if perfect else {}))
            current = audited.get(row['path'], {})
            current = current.get('modes', {}).get(str(index), {}) if index else current
            if current.get('charge') and abs(float(current['charge']['seconds']) - seconds) > 1e-6:
                disagreements.append(dict(name=row.get('nameEn'), mode=index, audited=current['charge'], native=seconds))
        if entry:
            record = dict(name=row.get('nameEn'), modes=entry)
            own = pkg._path_to_file(row['path'])
            if own.is_file():
                record['nativeSha256'] = hashlib.sha256(own.read_bytes()).hexdigest()
            out[row['path']] = record
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_charge_profiles.py',
                   semantics='per fire mode: charge seconds before each shot, divided by charge-rate mods and, when '
                             'chargeModifier is WEAPON_FIRE_RATE, by the fire-rate scale; audited charge entries win',
                   weapons=out, auditedDisagreements=disagreements)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(sum(len(r['modes']) for r in out.values()), 'charge modes in', len(out), 'weapons;', len(disagreements), 'audited disagreements')
    for d in disagreements:
        print('  disagree', d)


if __name__ == '__main__':
    main()
