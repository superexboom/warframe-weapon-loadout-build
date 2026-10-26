"""Inventory static projectile declarations without turning flags into combat rules.

Input is a current-installation extraction: objects.json and parents.json.
Output lists candidates for runtime/measurement checks; inheritance is resolved
and the declaring source of every relevant field is retained.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

FIELDS = ('AttackData','ExplosiveAttack','EmbedAttack','EmbedDeathAttack',
          'ExplosionDirectHitDamageHitType','IgnoreHeadShotBonus',
          'DealDamageThroughImpactBehavior','DamageRadius','EmbedDamageRadius',
          'CanStick','Embed','MaxBounces','OnProjectileDeathScript')


def inventory(objects, parents):
    rows=[]
    for path in sorted(objects):
        if not path.startswith('/Lotus/Weapons/'):
            continue
        chain=[];seen=set();p=path
        while p and p not in seen:
            chain.append(p);seen.add(p);p=parents.get(p)
        if not any(x == '/EE/Types/Engine/Projectile' or x.startswith('/Lotus/Types/Weapon/') and x.endswith('Projectile') for x in chain):
            continue
        declared={}
        for source in reversed(chain):
            for key,value in objects.get(source,{}).items():
                if key in FIELDS:declared[key]=dict(value=value,source=source)
        if not declared:continue
        checks=[]
        if 'ExplosionDirectHitDamageHitType' in declared:checks.append('explicit-explosion-direct-hit-type')
        if declared.get('IgnoreHeadShotBonus',{}).get('value'):checks.append('head-damage-and-event-eligibility-must-be-separated')
        if declared.get('EmbedDeathAttack',{}).get('value',{}).get('Amount',0)>0:checks.append('embedded-death-versus-radial-payload')
        if declared.get('ExplosiveAttack',{}).get('value',{}).get('Amount',0)>0:checks.append('irradiate-same-window-multiple-damage-events')
        if checks:rows.append(dict(path=path,checks=checks,fields=declared))
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--objects',type=Path,required=True);ap.add_argument('--parents',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    rows=inventory(json.loads(args.objects.read_text(encoding='utf-8')),json.loads(args.parents.read_text(encoding='utf-8')))
    result=dict(schema=1,classification='candidates-only-no-inferred-damage-multipliers',
                inputSha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.objects,args.parents)},
                count=len(rows),projectiles=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(count=len(rows),output=str(args.output))))


if __name__=='__main__':main()
