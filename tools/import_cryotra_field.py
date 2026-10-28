"""Draft Cryotra's native embedded Cold payload without mutating shared data.

Emits an export weapon patch and combat-reference entry for review. The replay
uses the existing single-target lingering contract: a target surviving the hit
receives ticks at0,1,2,3,4 seconds. Host-death persistence/spatial overlap and
boundary ordering remain diagnostics, never fabricated zero damage.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
from wfarsenal.packages import PackageIndex

WEAPON = '/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/CryoxionWeapon'
PROJECTILE = WEAPON.rsplit('/',1)[0] + '/CryoxionProjectile'


def build_draft(pkg, row, clock):
    if row.get('path') != WEAPON or row.get('slot') != 'companion':
        raise ValueError('Cryotra companion export required')
    native = pkg.resolve(WEAPON) or {}
    fire = next((v for b in native.get('Behaviors') or () for k,v in b.items()
                 if k.startswith('fire:') and isinstance(v,dict) and v.get('projectileType')), {})
    raw_path = fire.get('projectileType')
    projectile = raw_path if isinstance(raw_path,str) and raw_path.startswith('/') else WEAPON.rsplit('/',1)[0]+'/'+str(raw_path)
    if projectile != PROJECTILE or fire.get('fireIterations') != 1 or fire.get('IgnoreFireIterations'):
        raise ValueError('native Cryotra launch identity changed')
    record = pkg.resolve(projectile) or {}
    direct = record.get('AttackData') or {}
    embed = record.get('EmbedAttack') or {}
    duration = record.get('EmbedTime')
    modes = row.get('fireModes') or []
    if len(modes)!=1 or modes[0].get('index')!=0 or modes[0].get('damage',{}).get('types')!={'DT_IMPACT':10.}:
        raise ValueError('Cryotra export direct mode changed')
    if not record.get('Embed') or embed.get('Type')!='DT_FREEZE' or embed.get('Amount')!=20. or duration!=[5.,5.]:
        raise ValueError('native Cryotra field changed')
    if direct.get('ForcedProcs')!=['PT_CHILLED']:
        raise ValueError('native Cryotra direct Cold proc changed')
    if (clock.get('tick',{}).get('function')!='0x140297cf0'
            or 'delay=1.0f' not in clock.get('tick',{}).get('repeatSchedule','')
            or '0x140297cf0' not in clock.get('embedEntry',{}).get('immediateCall','')):
        raise ValueError('verified native embed clock required')
    patched=deepcopy(row)
    damage=patched['fireModes'][0]['damage']
    damage['projectile']=projectile
    damage['forcedProcs']=list(direct['ForcedProcs'])
    sources=[]
    for path in (WEAPON,projectile):
        file=pkg._path_to_file(path)
        if not file.is_file():file=file.with_suffix('.txt')
        if file.is_file():sources.append(dict(path=path,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    lingering=dict(damage={'cold':20.},tick_rate=1.,duration_seconds=5.,radius_m=float(record['EmbedDamageRadius']),
        falloff_start_m=0.,falloff_reduction=float(record['EmbedFallOff']),
        crit_chance=float(record['CriticalChance']),crit_multiplier=float(record['CriticalMultiplier']),
        status_chance=float(embed['ProcChance']),forcedProcs=list(embed.get('ForcedProcs') or []),
        stacking='stack',takes_condition_overload=False,
        nativeSource=projectile,nativeField='EmbedAttack',
        tickRateSource='native Projectile::DoEmbedDamage immediate + one-second scheduler')
    entry=dict(name='Cryotra',directTotal=10.,projectile=projectile,fireMode=0,
        scope='single stationary direct-hit target at field centre; immediate and 1s Cold ticks before 5s expiry',
        lingering=lingering,
        unmodeled=['cryotra-field-host-death-and-spatial-persistence-unverified',
                   'cryotra-field-overlap-unverified','cryotra-field-condition-overload-unverified',
                   'cryotra-embed-expiry-boundary-order-unverified'],
        lingeringSource=dict(nativeSources=sources,generatedBy='tools/import_cryotra_field.py',
            sourceBuild=clock.get('clientBuild'),clientSha256=clock.get('clientSha256'),
            nativeClock=clock.get('tick'),nativeEmbedEntry=clock.get('embedEntry')))
    return dict(weapon=patched,entry=entry,assumptions=dict(fieldCO='excluded pending validation',
        fieldStartsAt='direct impact; flight time omitted as in existing direct-hit replay',
        targetDeath='existing lingering per-victim generation; remaining field after target death unverified',
        maximumLife='flight3s; embed lifespan5s overrides expiration, same generic Embed entry as other fields'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages',type=Path,required=True)
    ap.add_argument('--clock',type=Path,required=True)
    ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():ap.error('use a new output to preserve evidence')
    pkg=PackageIndex(args.packages,json.loads((args.packages.parent/'parents.json').read_bytes()))
    row=next(w for w in json.loads(args.export.read_bytes())['data'] if w['path']==WEAPON)
    draft=build_draft(pkg,row,json.loads(args.clock.read_bytes()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(draft,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(args.output)

if __name__=='__main__':main()
