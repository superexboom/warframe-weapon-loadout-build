"""Recover Zylok duplex grouping and native Incarnon radial packets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
sys.path.insert(0,str(ROOT))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _sub_behaviour
from tools.refresh_spread_talons import preserve_lines


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    index=PackageIndex(args.packages,json.loads((args.packages.parent/'parents.json').read_bytes()))
    before=args.reference.read_bytes()
    reference=json.loads(before)
    rows=[]
    for weapon in json.loads(args.export.read_bytes())['data']:
        if weapon['nameEn'] not in {'Zylok','Zylok Prime'} or not weapon.get('isIncarnon'):
            continue
        native=index.resolve(weapon['path'])
        base_state=_sub_behaviour(native['Behaviors'][0],'state:')
        assert base_state['FireOnButtonAction']=='BOTH'
        impact=_sub_behaviour(native['Behaviors'][1],'impact:')
        radial=impact['RadialDamage']
        assert impact['ApplyRadialDamageOnHit']==1 and impact['MultiShotBuffsRadialDamage']==0
        spec=dict(damage={k:v*radial['baseAmount'] for k,v in radial['DamagePercent'].items() if v},
                  radius=radial['radius'],falloff=radial['fallOff'],crit_chance=radial['criticalChance'],
                  crit_multiplier=radial['criticalMultiplier'],status_chance=radial['baseProcChance'],
                  takes_multishot=False,takes_condition_overload=True)
        mode=weapon['fireModes'][1]
        profile=reference.setdefault('auditedAttacks',{}).setdefault(weapon['path'],{}).setdefault('modes',{}).setdefault('1',{})
        profile.update(allowIncarnon=True,directTotal=sum(mode['damage']['types'].values()),radial=spec)
        path=index._path_to_file(weapon['path']).with_suffix('.txt')
        rows.append(dict(weapon=weapon['path'],sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         duplex=base_state['FireOnButtonAction'],profile=profile))
    args.reference.write_bytes(preserve_lines(before,(json.dumps(reference,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    print('Zylok native profiles:',len(rows))


if __name__=='__main__':
    main()
