"""Restore authoritative fully charged projectiles without rebuilding other exports."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
sys.path.insert(0,str(ROOT))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _resolve_damage, _sub_behaviour, _extract_projectile_events
from tools.refresh_spread_talons import preserve_lines


def refresh(packages,export,repair_evidence=None):
    index = PackageIndex(packages,json.loads((packages.parent/'parents.json').read_text(encoding='utf-8-sig')))
    before = export.read_bytes()
    payload = json.loads(before)
    replacements, evidence = [], []
    repairs = {(row['weapon'],row['mode']):row['before'] for row in
               (json.loads(repair_evidence.read_bytes()).get('records') or [])} if repair_evidence else {}
    for weapon in payload['data']:
        if weapon.get('slot') not in {'primary','secondary','arch_gun'}:
            continue
        raw = index.resolve(weapon['path'])
        behaviors = raw.get(weapon.get('fireModeSource') or 'Behaviors') or []
        original = deepcopy(weapon)
        for mode in weapon.get('fireModes') or []:
            position = mode.get('index')
            if weapon.get('slot')=='arch_gun' and (weapon['path'],position) in repairs:
                mode['damage'] = deepcopy(repairs[(weapon['path'],position)])
                mode.pop('chargedProjectile',None)
            if not isinstance(position,int) or position>=len(behaviors):
                continue
            entry = behaviors[position]
            fire = _sub_behaviour(entry,'fire:') or {}
            state = _sub_behaviour(entry,'state:') or {}
            projectile_name=fire.get('chargedProjectileType') or fire.get('projectileType')
            from wfarsenal.extract import _resolve_weapon_reference
            delegate=not projectile_name or bool(_resolve_weapon_reference(index,weapon['path'],projectile_name)[1].get('DealDamageThroughImpactBehavior'))
            if (mode.get('trigger')=='/Lotus/Language/Menu/Loadout_TriggerCharge'
                    and delegate
                    and isinstance(state.get('DamageMultiplier'),(int,float)) and state['DamageMultiplier']>1):
                mode['chargeDamageMultiplier']=state['DamageMultiplier']
                mode['chargeTime']=state.get('ChargeTime',state.get('chargeTime'))
            elif mode.get('trigger')=='/Lotus/Language/Menu/Loadout_TriggerCharge':
                mode.pop('chargeDamageMultiplier',None)
            charged = fire.get('chargedProjectileType')
            if not isinstance(charged,str) or not charged:
                continue
            selected = {**fire,'projectileType':charged}
            damage = _resolve_damage(index,weapon['path'],selected,_sub_behaviour(entry,'impact:') or {})
            if not damage or not damage.get('types') or not damage.get('projectile'):
                raise ValueError('charged projectile did not resolve: '+weapon['path'])
            old_damage = deepcopy(mode['damage'])
            mode['damage'] = damage
            mode['chargedProjectile'] = True
            charge = state.get('ChargeTime',state.get('chargeTime'))
            if isinstance(charge,(int,float)) and charge>=0:
                mode['chargeTime'] = charge
            event_layer = _extract_projectile_events(index,weapon['path'],selected)
            for key in ('projectileEvents','eventDamage'):
                mode.pop(key,None)
            mode.update(event_layer or {})
            path = index._path_to_file(damage['projectile'])
            if not path.is_file():
                path = path.with_suffix('.txt')
            evidence.append(dict(weapon=weapon['path'],name=weapon['nameEn'],mode=position,
                                 before=old_damage,after=damage,chargeSeconds=charge,
                                 projectileSha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                                 ancestry=index.ancestry(damage['projectile'])))
        if original!=weapon:
            replacements.append((original,weapon))
    text = before.decode('utf-8').replace('\r\n','\n')
    for old,new in replacements:
        serialize = lambda value: json.dumps(value,ensure_ascii=False,sort_keys=True,indent=1).replace('\n','\n  ')
        previous = serialize(old)
        if text.count(previous)!=1:
            raise ValueError('ambiguous weapon record: '+old['path'])
        text = text.replace(previous,serialize(new),1)
    export.write_bytes(preserve_lines(before,text.encode('utf-8')))
    return dict(sourceBuild=packages.parent.name,weapons=len(replacements),modes=len(evidence),
                beforeSha256=hashlib.sha256(before).hexdigest(),afterSha256=hashlib.sha256(export.read_bytes()).hexdigest(),records=evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--repair-from',type=Path)
    args = parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    result = refresh(args.packages,args.export,args.repair_from)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('weapons','modes','sourceBuild')}))


if __name__=='__main__':
    main()
