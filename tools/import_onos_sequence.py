"""Bind Onos charge, blast and radial packets to their native behaviours."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
sys.path.insert(0,str(ROOT))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _sub_behaviour
from tools.refresh_spread_talons import preserve_lines


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    index=PackageIndex(args.packages,json.loads((args.packages.parent/'parents.json').read_bytes()))
    path='/Lotus/Weapons/Thanotech/EntratiWristGun/EntratiWristGunWeapon'
    native=index.resolve(path)
    beam=native['Behaviors'][1]
    power=native['Behaviors'][2]
    fire=_sub_behaviour(beam,'fire:')
    state=_sub_behaviour(beam,'state:')
    power_state=_sub_behaviour(power,'state:')
    impact=_sub_behaviour(power,'impact:')
    raw_radial=impact['RadialDamage']
    sequence=dict(alignmentShots=state['FullAlignmentShotsRequirement'],powerCost=power_state['ChargesToConsumePerShot'],
                  postFireSeconds=power_state['PostFirePauseTime'],rampSeconds=fire['ChargeUp']['ChargeUpTime'],
                  rampMaximum=(_sub_behaviour(beam,'impact:')['ContinuousDamageAttenuation'])[1],
                  timingSource='native-alignment-shots-and-held-fire-rate')
    radial=dict(damage={k:v*raw_radial['baseAmount'] for k,v in raw_radial['DamagePercent'].items() if v},radius=raw_radial['radius'],
                crit_chance=raw_radial['criticalChance'],crit_multiplier=raw_radial['criticalMultiplier'],
                status_chance=raw_radial['baseProcChance'],takes_condition_overload=False,takes_multishot=False,
                requiresOnosRadialHit=True,falloff=raw_radial['fallOff'])
    before=args.reference.read_bytes()
    payload=json.loads(before)
    modes=payload.setdefault('auditedAttacks',{}).setdefault(path,{}).setdefault('modes',{})
    modes['1']={**modes.get('1',{}),'allowIncarnon':True,'directTotal':30.,'onosCharge':sequence}
    modes['2']={**modes.get('2',{}),'allowIncarnon':True,'directTotal':2200.,'onosCharge':sequence,'radial':radial}
    source=args.packages/'Lotus/Weapons/Thanotech/EntratiWristGun/EntratiWristGunWeapon.txt'
    evidence=dict(weapon=path,nativeSourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),sequence=sequence,radial=radial)
    args.reference.write_bytes(preserve_lines(before,(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    main()
