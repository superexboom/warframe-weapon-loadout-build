"""Bind confirmed Incarnon radial packets to their native attack components."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
sys.path.insert(0,str(ROOT))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _sub_behaviour
from tools.refresh_spread_talons import preserve_lines


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--wfsim',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    index=PackageIndex(args.packages,json.loads((args.packages.parent/'parents.json').read_bytes()))
    before=args.reference.read_bytes()
    reference=json.loads(before)
    records=[]
    revision=subprocess.check_output(['git','-C',str(args.wfsim),'rev-parse','HEAD'],text=True).strip()
    for weapon in json.loads(args.export.read_bytes())['data']:
        incarnation=reference['incarnon'].get(weapon['path']) or {}
        if (weapon.get('slot')=='melee' or not incarnation.get('radial')
                or incarnation.get('referenceId') in {'burston_incarnon','burston_prime_incarnon'}):
            continue
        native=index.resolve(weapon['path'])
        for i,mode in enumerate(weapon['fireModes']):
            if not mode.get('isIncarnonForm'):
                continue
            damage=mode['damage']
            impact=_sub_behaviour(native['Behaviors'][mode['index']],'impact:') or {}
            raw=impact.get('RadialDamage') or {}
            radial=dict(takes_condition_overload=bool(incarnation['radial'].get('takes_condition_overload')),
                        takes_multishot=bool(incarnation['radial'].get('takes_multishot',True)))
            source=weapon['path']
            if raw.get('baseAmount') and impact.get('ApplyRadialDamageOnHit'):
                radial.update(damage={k:v*raw['baseAmount'] for k,v in raw['DamagePercent'].items() if v},
                              radius=raw['radius'],crit_chance=raw['criticalChance'],crit_multiplier=raw['criticalMultiplier'],
                              status_chance=raw['baseProcChance'],falloff=raw['fallOff'],
                              takes_multishot=bool(impact.get('MultiShotBuffsRadialDamage')))
            else:
                candidates=[c for c in damage.get('components') or [] if c.get('types') and c.get('radius')
                            and c.get('source') in {'ExplosiveAttack','EmbedDeathAttack'}]
                if not candidates or not damage.get('projectile'):
                    continue
                # Only the confirmed principal packet is selected; a second
                # inherited attack is not proof of another explosion.
                component=candidates[0]
                source=damage['projectile']
                projectile=index.resolve(source)
                radial.update(damage=component['types'],radius=component['radius'],falloff=component['falloff'],
                              crit_chance=damage['critChance'],crit_multiplier=damage['critMultiplier'],
                              status_chance=component['procChance'])
                if component.get('forcedProcs'):
                    radial['forcedProcs']=component['forcedProcs']
                if component['source']=='EmbedDeathAttack':
                    delay=projectile.get('EmbedTime')
                    if not delay or delay[0]!=delay[1]:
                        raise ValueError('native embed time not deterministic: '+source)
                    radial['impact_delay_seconds']=delay[0]
            profile=reference.setdefault('auditedAttacks',{}).setdefault(weapon['path'],{}).setdefault('modes',{}).setdefault(str(i),{})
            profile.update(allowIncarnon=True,directTotal=sum(damage['types'].values()),radial=radial)
            if damage.get('projectile'):
                profile['projectile']=damage['projectile']
            if mode['trigger']=='/Lotus/Language/Menu/Loadout_TriggerCharge' and not mode.get('chargeTime'):
                path=args.wfsim/incarnation['source']
                seconds=(yaml.safe_load(path.read_text(encoding='utf-8')).get('attack') or {}).get('charge_seconds')
                if seconds:
                    profile['charge']=dict(seconds=seconds,source='WFSim-charge-duration-native-default-not-serialized',revision=revision)
            path=index._path_to_file(source).with_suffix('.txt')
            records.append(dict(name=weapon['nameEn'],weapon=weapon['path'],mode=i,source=source,
                                sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),profile=profile,
                                coAndMultishotSource=incarnation['source'],referenceRevision=revision))
    args.reference.write_bytes(preserve_lines(before,(json.dumps(reference,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print('Incarnon radial profiles:',len(records))


if __name__=='__main__':
    main()
