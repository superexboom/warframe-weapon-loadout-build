"""Import current-package stackable attacks with separately audited native defaults."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from wfarsenal.packages import PackageIndex
from tools.refresh_spread_talons import preserve_lines


def import_profiles(packages, export, reference):
    pkg = PackageIndex(packages, json.loads((packages.parent/'parents.json').read_text(encoding='utf-8-sig')))
    weapons = json.loads(export.read_bytes())['data']
    original = reference.read_bytes()
    payload = json.loads(original)
    evidence = []
    def source(path):
        file = pkg._path_to_file(path)
        if not file.is_file():
            file = file.with_suffix('.txt')
        return dict(path=path, sha256=hashlib.sha256(file.read_bytes()).hexdigest())
    def component(attack, raw, *, fallback_type=None, fallback_crit=None):
        return dict(damage={attack.get('Type',fallback_type):float(attack.get('Amount') or 0)},
                    critChance=float(raw.get('CriticalChance',fallback_crit or 0)),
                    critMultiplier=float(raw.get('CriticalMultiplier',1)),
                    statusChance=float(attack.get('ProcChance') or 0),
                    forcedProcs=attack.get('ForcedProcs') or [],
                    takesConditionOverload=bool(raw.get('DealDamageThroughImpactBehavior')))
    for w in weapons:
        if w.get('nameEn') not in ('Stug','Simulor','Synoid Simulor'):
            continue
        for i, mode in enumerate(w['fireModes']):
            path = mode['damage']['projectile']
            raw = pkg.resolve(path)
            kind = 'stug' if w['nameEn']=='Stug' else 'simulor'
            max_stack = int(raw.get('MaxProjectileStack',10))
            profile = dict(kind=kind, maxStack=max_stack, initialStack=1,
                           resetLifeOnStack=bool(raw.get('ResetMaxLifeOnStack')),
                           stackedLife=float(raw.get('StackedMaxLife',raw.get('MaxLife',8))),
                           maxLife=float(raw.get('MaxLife',8)),
                           attachAtStack=int(raw.get('AttachSpecialAtThisStack') or 0),
                           stackHitProxyDamage=bool(raw.get('StackHitProxyDamage')),
                           nativeSources=[source(path)], sourceBuild=packages.parent.name)
            if kind=='stug':
                if raw.get('EmbedTime')!=[1.5,1.5] or raw.get('Embed')!=1:
                    raise ValueError('Stug embed identity changed')
                # The stacking rule lives in GooGun.lua (OnProjectileStacked), not
                # in fields: the blob lives EmbedTime after it sticks and every
                # new stack refreshes that life (wiki Stug); MaxLife 8 is flight.
                profile.update(embedSeconds=1.5, embedInterval=1., resetLifeOnStack=True, stackedLife=1.5,
                               lifeSource='native EmbedTime 1.5; refresh per stack from GooGun.lua behaviour (wiki Stug)',
                               embed=component(raw['EmbedAttack'],raw),
                               explosion=component(raw['EmbedDeathAttack'],raw))
                if i==1:
                    profile['chargedStacks'] = True
                if i==2:
                    script=raw['OnProjectileDeathScript']
                    if (script.get('Function')!='OnIncarnonProjectileDeath' or script.get('_maxSecondaryProjectilesCount')!=5
                            or script.get('_maxExplosiveBounces')!=2 or script.get('_deathExplosionMult')!=2.5):
                        raise ValueError('Stug child identity changed')
                    child_path=path.rsplit('/',1)[0]+'/'+script['_secondaryProjectile']
                    child=pkg.resolve(child_path)
                    profile.update(child=component(child['ExplosiveAttack'],child), childMaxCount=5,
                                   childMinCount=2, childLife=float(child['MaxLife']),
                                   childBounceCount=int(script['_maxExplosiveBounces']),
                                   childDeathMultiplier=float(script['_deathExplosionMult']))
                    profile['nativeSources'].append(source(child_path))
            else:
                if max_stack!=4 or raw.get('StackedMaxLife')!=20 or raw.get('AttachSpecialAtThisStack')!=4:
                    raise ValueError('Simulor merge identity changed')
                profile.update(explosion=component(raw['ExplosiveAttack'],raw),
                               merge=component(raw['StackingAttack'],raw),
                               mergeDamage=raw['StackingDamage'],mergeRadius=raw['StackingDamageRange'])
                special=raw['SpecialAttachEntity']['Type']
                special_raw=pkg.resolve(special)
                hole_path='/Lotus/Weapons/Cephalon/Primary/CephPrimary/CephPrimaryBlackHole'
                if not any(c.get('Type')==hole_path for c in special_raw.get('CreatedTypes') or []):
                    raise ValueError('Simulor singularity reference changed')
                hole=pkg.resolve(hole_path)
                if hole['DamageData']['Amount']!=200 or hole['DamageOverTimeInterval']!=.25:
                    raise ValueError('Simulor singularity damage changed')
                # BlackHole ctor 141873930 initializes DamageData type=10
                # (DT_MAGNETIC); 14126b120 scales damage by exposure time,
                # with weapon damage/status and elemental modifier lookups.
                profile['singularity']=component(hole['DamageData'],{},fallback_type='DT_MAGNETIC')
                profile['singularity'].update(interval=.25,damagePerSecond=True,critChance=0.,critMultiplier=1.)
                profile['nativeSources'] += [source(special),source(hole_path)]
            entry=payload['auditedAttacks'][w['path']]
            if i:
                entry=entry['modes'][str(i)]
            entry['stackable']=profile
            entry['unmodeled']=[n for n in entry.get('unmodeled') or [] if n not in {
                'stug-projectile-stack-lifecycle-unmodeled','stug-embed-ticks-unmodeled',
                'stug-full-charge-stack-unmodeled','stug-bouncing-child-contact-unmodeled',
                'orb-merging-and-singularity-unmodeled','orb-multishot-merging-economy-unmodeled'}]
            if kind=='stug' and i==1:
                entry['charge'] = dict(seconds=2.,source='native-ChargeTime')
                entry['unmodeled'] = [n for n in entry['unmodeled'] if n!='stug-charged-ammo-stack-input-required']
            evidence.append(dict(name=w['nameEn'],mode=i,profile=deepcopy(profile)))
    reference.write_bytes(preserve_lines(original,(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    return evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    rows=import_profiles(args.packages,args.export,args.reference)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('imported stackable modes:',len(rows))


if __name__=='__main__':
    main()
