"""Import exact native projectile emission locks without granting chain or field damage.

IgnoreFireIterations selects raw fireIterations in the original shared consumer
0x140f75d20. It is not a rule that every secondary mode ignores multishot.
"""
from __future__ import annotations
import argparse,json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from tools.import_native_secondary_payloads import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,sha256,source_rows
from tools.refresh_spread_talons import preserve_lines
ROOT=Path(__file__).resolve().parents[1]
FIRE='/Lotus/Types/Game/LotusWeaponProjectileFireBehavior'


def updates(packages,rows):
    changes=[];deferred=[]
    for original in rows:
        if original.get('slot') not in ('primary','secondary','arch_gun','companion'):continue
        weapon=deepcopy(original);raw=packages.resolve(weapon['path'])
        bank=weapon.get('fireModeSource') or ('HeavyBehaviors' if weapon.get('slot')=='arch_gun' and raw.get('HeavyBehaviors') else 'Behaviors')
        behaviors=raw.get(bank) or [];admitted=[]
        for ordinal,mode in enumerate(weapon.get('fireModes') or []):
            if mode.get('behaviorKind')=='auxiliary-melee' or mode.get('isIncarnonForm'):continue
            index=mode.get('index',ordinal)
            if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(behaviors):continue
            behavior=behaviors[index];fire=behavior.get('fire:LotusWeaponProjectileFireBehavior') or {}
            if behavior.get('fire:Type')!=FIRE or fire.get('IgnoreFireIterations')!=1:continue
            damage=mode.get('damage') or {};projectile=damage.get('projectile')
            if not projectile or not damage.get('types'):
                deferred.append(dict(path=weapon['path'],mode=ordinal,reason='no evaluable projectile identity; keep source declaration separate'));continue
            source=fire.get('chargedProjectileType') if mode.get('chargedProjectile') else fire.get('projectileType')
            if not source or packages.locate(weapon['path'],source)!=projectile:
                raise ValueError('native selected projectile changed: '+weapon['path'])
            count=fire.get('fireIterations')
            if not isinstance(count,int) or isinstance(count,bool) or count<=0 or mode.get('multishot')!=count:
                raise ValueError('native raw projectile count changed: '+weapon['path'])
            if fire.get('AttenuateFireIterationsForCharge') not in (None,0) or fire.get('AttenuateForCharge') not in (None,0):
                raise ValueError('charge-dependent projectile emission requires separate admission')
            mode['nativeIgnoreFireIterations']=True
            admitted.append(dict(mode=ordinal,nativeIndex=index,bank=bank,projectile=projectile,rawCount=count))
        if admitted:changes.append(dict(path=weapon['path'],name=weapon.get('nameEn'),before=original,after=weapon,modes=admitted,nativeSources=source_rows(packages,[weapon['path']])))
    return changes,deferred


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True)
    ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    if args.evidence.exists():ap.error('preserve evidence: choose new path')
    if sha256(args.client_exe)!=CLIENT_SHA256:raise ValueError('native image changed')
    package=AuditedPackages(args.packages_bin);package.own=lru_cache(None)(package.own)
    original=args.export.read_bytes();changes,deferred=updates(package,json.loads(original)['data'])
    if not changes:raise ValueError('no admitted projectile locks')
    # Normalize once, replace exact bounded records, then restore unchanged
    # lines once. Re-diffing the entire catalogue for each weapon is quadratic.
    text=original.decode('utf8').replace('\r\n','\n')
    for item in changes:
        if item['before']==item['after']:continue
        before=json.dumps(item['before'],ensure_ascii=False,indent=1,sort_keys=True).replace('\n','\n  ')
        after=json.dumps(item['after'],ensure_ascii=False,indent=1,sort_keys=True).replace('\n','\n  ')
        if text.count(before)!=1:raise ValueError('export record layout ambiguous')
        text=text.replace(before,after,1)
    unchanged=all(item['before']==item['after'] for item in changes)
    changed=original if unchanged else preserve_lines(original,text.encode('utf8'))
    if args.apply:args.export.write_bytes(changed)
    result=dict(clientSha256=CLIENT_SHA256,packagesSha256=PACKAGE_SHA256,applied=args.apply,
        sourceConsumer='0x140f75d20: fire+0x148 true returns raw fireIterations+0x28; weapon multishot query skipped',
        count=len(changes),modes=sum(len(r['modes']) for r in changes),deferred=deferred,
        rows=[{k:v for k,v in row.items() if k not in ('before','after')} for row in changes],
        limits=['Emission count only; chain budgets, charge damage, repeated contacts, geometry, and other child sources are separate consumers.'])
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    with args.evidence.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(dict(weapons=result['count'],modes=result['modes'],deferred=len(deferred),applied=args.apply)))


if __name__=='__main__':main()
