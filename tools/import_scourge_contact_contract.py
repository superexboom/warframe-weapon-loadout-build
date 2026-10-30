"""Scourge Prime native55 contact contract; cadence remains evidence-only.

No production scoring patch is emitted. Single physical throw count and native
contact55 are independent of active-spear/reload/recall cadence.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from tools.import_native_secondary_payloads import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,source_rows,sha256
ROOT=Path(__file__).resolve().parents[1]
WEAPON='/Lotus/Weapons/Tenno/LongGuns/PrimeScourge/PrimeScourgeWeapon'
PROJECTILE='/Lotus/Weapons/Tenno/LongGuns/PrimeScourge/PrimeScourgeChargedProjectile'
ANCESTRY=[PROJECTILE,'/Lotus/Weapons/Tenno/LongGuns/TnPriestSpear/TnPriestSpearChargedProjectile',
 '/Lotus/Weapons/Tenno/LongGuns/TnPriestSpear/TnPriestSpearProjectile','/Lotus/Types/Weapons/BoltoProjectile','/Lotus/Types/Weapon/BoltoProjectile']
BOUNDS=['scourge-prime-active-spear-throw-recall-rethrow-cadence-unmodeled',
 'scourge-prime-stopped-embedded-script-payload-unmodeled',
 'scourge-prime-contact-geometry-and-source-snapshot-unverified',
 'scourge-prime-main55-CO-weakpoint-events-unverified']
def build_contract(pkg,row):
    if row.get('path')!=WEAPON or row['fireModes'][1]['damage'].get('projectile')!=PROJECTILE:raise ValueError('Scourge selected export identity changed')
    if abs(sum(row['fireModes'][1]['damage']['types'].values())-300.)>.02:raise ValueError('Scourge direct packet changed')
    chain=[];p=PROJECTILE
    while p:chain.append(p);p=pkg.parent(p)
    if chain!=ANCESTRY:raise ValueError('Scourge Bolto ancestry changed')
    p=pkg.resolve(PROJECTILE);w=pkg.resolve(WEAPON);mode=w['Behaviors'][1]
    fire=next(v for k,v in mode.items() if k.startswith('fire:') and isinstance(v,dict));state=next(v for k,v in mode.items() if k.startswith('state:') and isinstance(v,dict))
    if (fire.get('IgnoreFireIterations')!=1 or fire.get('fireIterations')!=1
            or pkg.locate(WEAPON,fire.get('chargedProjectileType'))!=PROJECTILE):raise ValueError('Scourge one-spear emission changed')
    required=dict(ExplodeOnImpact=1,CanExplodeOnContact=0,StopOnAvatars=1,DamageRadius=7,ExplosionFallOff=.60000002,MaxLife=20,EmbedTime=[10,10],SetLifeOnImpact=1,ScriptsPreventDestruction=1)
    if any(p.get(k)!=v for k,v in required.items()) or p.get('ExplodeOnLifeExpired',0)!=0:raise ValueError('Scourge contact/lifecycle changed')
    a=p.get('ExplosiveAttack') or {}
    if (a.get('Type')!='DT_CORROSIVE' or a.get('Amount')!=55 or a.get('ProcChance')!=.30000001
            or p.get('CriticalChance')!=.1 or p.get('CriticalMultiplier')!=2):raise ValueError('Scourge main55 packet changed')
    lifecycle=dict(TrackProjectiles=1,MaxNumProjectiles=1,DestroyActiveProjectiles=1,ReloadAfterEveryShot=1,DetonateOnSwapToPrimary=1,HideAttachAndDisableWeapon=1)
    if any(state.get(k)!=v for k,v in lifecycle.items()):raise ValueError('Scourge throw/recall state changed')
    proof=dict(clientSha256=CLIENT_SHA256,packageSha256=PACKAGE_SHA256,nativeSources=source_rows(pkg,[WEAPON,PROJECTILE]),
      classTable='BoltoProjectile0x14226a010; contact+5781409397f0,embed+738140f25fa0,death+768140163a60,launch+780140f874b0',
      contact='ordinary accepted avatar path14093a12c..a66b reaches14093a64d radial+7b8 exactlyonce with16d0 ExplodeOnImpact1,7f0StopOnAvatars1,c250',
      specialContact='CanExplodeOnContact mapsBolto+1930;1407d5cd9false returnsfalse without special source; not a veto of normal16d0 branch',
      alternatives='five+7b8sites are mutually selected collision/alias/static branches, not five packets on one contact; verified ordinary path usesa64d only',
      payload='normalc250 ->common+63014160c5a0 selectsExplosiveAttack+5b4=55; explicit laterc251 would selectEmbedDeathAttack+9c8,not55',
      death='normalc250 andExplodeOnImpact1 causes140163b01..b22 to skipdeathradial; contactthenplaindeath remainsone',
      count='IgnoreFireIterations at +0x148 = 1 makes full 0x140f75d20 return raw count at +0x28 = 1; no weapon multishot query; one physical spear per throw',
      stateFields='state serializer140655d47TrackProjectiles+60;140655d6aMaxNumProjectiles+68;14182c531ReloadAfterEveryShot+1a5;14182c557DestroyActiveProjectiles+1a6;14182c57dDetonateOnSwap+1a7;14182c5a3HideDisable+1a8',
      reloadConsumer='LotusSpearGunStateBehavior142362460+3f0 ->1411e83c0 reads1a5 and dispatches+1681402d4e10; flagtrue has explicit8/0/11state requests depending caller/weapon conditions; not just panel fireRate',
      limits=list(BOUNDS))
    return dict(schemaVersion=1,kind='native-scourge-contact-evidence-only',weapons={},pending=[dict(path=WEAPON,mode=1,candidateOnly=True,defaultScoringExcluded=True,
      reason='single contact55 proven; active-spear destroy/recall/reload cadence and embed lifecycle require independent engine interface',
      sourcePayload=dict(directTotal=300.,radial=dict(damage={'corrosive':55.},critChance=.1,critMultiplier=2.,statusChance=.30000001,radius_m=7.,falloff=.60000002,
        delayFromAcceptedContactSeconds=0.,packetsPerPhysicalThrow=1,physicalThrowsPerFire=1,scalarMultishotAllowed=False),nativeThrowState=lifecycle),unmodeled=list(BOUNDS),evidence=proof)])
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True);ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():ap.error('choose new evidence output')
    if sha256(a.client_exe)!=CLIENT_SHA256:raise ValueError('nativeEXE changed')
    row=next(r for r in json.loads(a.export.read_bytes())['data'] if r['path']==WEAPON);out=build_contract(AuditedPackages(a.packages_bin),row);a.output.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8');print('PASS Scourge Prime contact55,0admitted,1cadencepending')
if __name__=='__main__':main()
