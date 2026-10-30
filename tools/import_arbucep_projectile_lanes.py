"""Import hash-pinned Arbucep lane payloads and native selector contract."""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
from functools import lru_cache
try:
    from .import_native_secondary_payloads import AuditedPackages,source_rows,CLIENT_SHA256,PACKAGE_SHA256
    from .import_projectile_components import apply_native_contract
except ImportError:  # direct CLI invocation
    from import_native_secondary_payloads import AuditedPackages,source_rows,CLIENT_SHA256,PACKAGE_SHA256
    from import_projectile_components import apply_native_contract
PATH='/Lotus/Weapons/Tenno/Archwing/Primary/NokkoArchGun/NokkoArchGun'
ELEMENTS=('EXPLOSION','CORROSIVE','GAS','MAGNETIC','RADIATION','VIRAL')
BOUNDS=['arbucep-projectile-contact-and-radial-centre-coverage-idealized',
        'arbucep-innate-mushroom-and-ammo-deco-script-unmodeled']

def extract(pkg):
    raw=pkg.resolve(PATH);b=raw['HeavyBehaviors'][0];f=b['fire:LotusWeaponProjectileFireBehavior']
    if (f['fireIterations']!=6 or f['projectileType'] or f['chargedProjectileType']
        or f['advanceProjectileSequenceOnFire']!=1 or f['MultiShotProjectileType']!='NokkoArchGunGuidedBlastProj'
        or f['MultiShotChargedProjectileType'] or len(f['projectileSequenceList'])!=6):raise ValueError('Arbucep native selector changed')
    lanes=[];paths=[]
    for i,(ref,element) in enumerate(zip(f['projectileSequenceList'],ELEMENTS)):
        path=pkg.locate(PATH,ref);p=pkg.resolve(path);a=p['AttackData'];r=p['ExplosiveAttack'];dtype='DT_'+element
        if a['Amount']!=32 or r['Amount']!=228 or a['Type']!=dtype or r['Type']!=dtype or p['DamageRadius']!=4:
            raise ValueError('Arbucep native packet changed')
        if a['ProcChance']!=2.0940001 or r['ProcChance']!=2.0940001 or p['CriticalChance']!=.1 or p['CriticalMultiplier']!=2.9000001:
            raise ValueError('Arbucep native packet chance changed')
        packet=dict(types={dtype:32.},procChance=a['ProcChance'],forcedProcs=list(a.get('ForcedProcs') or []),
                    critChance=p['CriticalChance'],critMultiplier=p['CriticalMultiplier'],projectile=path,
                    nativeSource=path,nativeField='AttackData',impact_delay_seconds=0.,
                    takes_condition_overload=True,takes_victim_crit=True,
                    coProfile=dict(behavior='independent',baseFraction=1.,excludeFlatSources=[]))
        radial=dict(damage={dtype:228.},radius_m=4.,falloff_start_m=0.,falloff_reduction=float(p.get('ExplosionFallOff',0.)),
            status_chance=r['ProcChance']/6,crit_chance=p['CriticalChance'],crit_multiplier=p['CriticalMultiplier'],
            takes_multishot=False,takes_condition_overload=False,nativeSource=path,nativeField='ExplosiveAttack',
            impact_delay_seconds=0.,forcedProcs=list(r.get('ForcedProcs') or []))
        apply_native_contract(packet)
        apply_native_contract(radial)
        lanes.append(dict(index=i,projectile=path,direct=packet,radial=radial));paths.append(path)
    entry=dict(name='Arbucep',fireMode=0,projectileLanes=dict(kind='cyclic-physical-projectile',length=6,rawFireIterations=6,
        extraPolicy='continue-sequence',initialPhase=0,lanes=lanes),unmodeled=BOUNDS,
        nativeSources=source_rows(pkg,[PATH,*paths]),packageSha256=PACKAGE_SHA256,
        nativeEvidence=dict(clientSha256=CLIENT_SHA256,selector='0x140e496d0 -> 0x141809340; null+6c8 blocks MS override',
            advance='0x14126e103..0x14126e13f every physical spawn',count='0x140f75d71..0x140f75e16 floor + Bernoulli',
            status='raw2.0940001 / basefireIterations6; not modded total'))
    return dict(schemaVersion=1,kind='auditedAttacks-mode-merge',weapons={PATH:{'0':entry}})

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():ap.error('preserve evidence: output already exists')
    if hashlib.sha256(a.client_exe.read_bytes()).hexdigest()!=CLIENT_SHA256:raise ValueError('native client changed')
    pkg=AuditedPackages(a.packages_bin);pkg.own=lru_cache(maxsize=None)(pkg.own);patch=extract(pkg)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf8') as f:json.dump(patch,f,ensure_ascii=False,indent=2);f.write('\n')
    print('Arbucep1mode6physical lanes:',a.output)
if __name__=='__main__':main()
