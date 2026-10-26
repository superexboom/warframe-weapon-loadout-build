"""Import per-attack GunCO behavior from a pinned WFSim reference checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.refresh_spread_talons import preserve_lines


def identifier(name):
    return re.sub(r'[^a-z0-9]+','_',name.casefold()).strip('_')


def import_reference(source, export, reference):
    revision = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    rows = []
    for path in sorted((source/'data/weapons').rglob('*.yaml')):
        row = yaml.safe_load(path.read_text(encoding='utf-8'))
        if isinstance(row,dict) and row.get('co_behavior') in {'independent','additive_with_base_damage','inert'}:
            rows.append((row,path))
    evolutions = []
    for path in sorted((source/'data/evolutions').glob('*.yaml')):
        row = yaml.safe_load(path.read_text(encoding='utf-8'))
        if row.get('co_base_excludes_this_evolution'):
            evolutions.append((row,path))
    profiles = {}
    for weapon in json.loads(export.read_bytes())['data']:
        if weapon.get('slot') not in {'primary','secondary','arch_gun'}:
            continue
        key = identifier(weapon.get('nameEn') or '')
        candidates = [(row,path) for row,path in rows if row.get('id')==key or row.get('transform_group')==key]
        if not candidates:
            continue
        by_mode = {}
        modes = weapon.get('fireModes') or []
        for i,mode in enumerate(modes):
            incarnon = bool(mode.get('isIncarnonForm'))
            options = [(row,path) for row,path in candidates if (row.get('form')=='incarnon')==incarnon]
            if not options:
                continue
            damage = mode.get('damage') or {}
            def difference(option):
                attack = option[0].get('attack') or {}
                total = sum((attack.get('damage') or {}).values())
                native_total = sum((damage.get('types') or {}).values())*float(mode.get('chargeDamageMultiplier') or 1.)
                return (abs(float(attack.get('crit_chance') or 0)-float(damage.get('critChance') or 0))*20
                        +abs(total-native_total)/max(native_total,1)
                        +abs(float(attack.get('fire_rate') or 0)-float(mode.get('fireRate') or 0))/max(float(mode.get('fireRate') or 1),1))
            row,path = min(options,key=difference)
            if difference((row,path))>1.5:
                continue
            exclusions = []
            for evo,_ in evolutions:
                if evo.get('weapon')!=key or (evo.get('co_base_excludes_only_form') and
                    evo['co_base_excludes_only_form']!=('incarnon' if incarnon else 'base')):
                    continue
                amounts = [float(e['value']) for e in evo.get('effects') or [] if e.get('kind')=='flat_base_damage']
                if len(amounts)!=1:
                    continue
                for tier in (weapon.get('incarnon') or {}).get('tiers') or []:
                    if tier['tier']!=evo['tier']:
                        continue
                    for branch in tier['branches']:
                        for effect in branch.get('effects') or []:
                            if (effect.get('upgradeType')=='WEAPON_DAMAGE_AMOUNT' and effect.get('operation')=='ADD_BASE'
                                    and not effect.get('isSubUpgrade') and abs(effect['valuePerRank']-amounts[0])<1e-5):
                                exclusions.append(effect.get('sourcePath') or branch['path'])
            by_mode[str(i)] = dict(behavior=row['co_behavior'],baseFraction=0. if row['co_behavior']=='inert' else float(row.get('co_base_fraction',1.)),
                                  excludeFlatSources=sorted(set(exclusions)),projectile=damage.get('projectile'),
                                  directTotal=sum((damage.get('types') or {}).values()),source=path.relative_to(source).as_posix(),
                                  sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),revision=revision)
        if by_mode:
            profiles[weapon['path']] = by_mode
    before = reference.read_bytes()
    payload = json.loads(before)
    payload['coProfiles'] = profiles
    reference.write_bytes(preserve_lines(before,(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    return dict(revision=revision,weapons=len(profiles),modes=sum(len(v) for v in profiles.values()),profiles=profiles)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args = parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence path')
    result = import_reference(args.source,args.export,args.reference)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('revision','weapons','modes')}))


if __name__=='__main__':
    main()
