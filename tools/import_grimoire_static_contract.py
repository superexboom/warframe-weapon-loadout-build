"""Extract Grimoire source contract and explicit optional coverage metadata.

Physical contact has no damage submitter. Periodic chains and launch expiry
require the selected original-recipient coverage policy; no fixed hit-relative
radial or unconditional secondary packet is imported.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from tools.import_native_secondary_payloads import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,source_rows,sha256
ROOT=Path(__file__).resolve().parents[1]
WEAPON='/Lotus/Weapons/Tenno/Grimoire/TnGrimoire'
PROJECTILE='/Lotus/Weapons/Tenno/Grimoire/TnGrimoireAltProj'
BOUNDS=['grimoire-alt-select-coverage-strategy']

def build_contract(pkg,row):
    if row.get('path')!=WEAPON or row['fireModes'][1]['damage'].get('projectile')!=PROJECTILE:
        raise ValueError('Grimoire exported projectile changed')
    if abs(sum(row['fireModes'][1]['damage']['types'].values())-350.)>.001:
        raise ValueError('Grimoire direct payload changed')
    if pkg.parent(PROJECTILE)!='/EE/Types/Game/PlayerChainingProjectile':raise ValueError('Grimoire class changed')
    p=pkg.resolve(PROJECTILE);w=pkg.resolve(WEAPON)
    required=dict(MaxLife=6,ExplodeOnLifeExpired=1,DamageRadius=6,ExplosionFallOff=.80000001,
        BounceOnAvatars=0,StopOnAvatars=0,KinematicMovement=1,KinematicInitialSpeed=6,KinematicMinSpeed=1.75,KinematicMaxSpeed=6,
        KinematicPostCollisionsSpeedFactor=.25,MaxTargetsPerAttack=3,MaxChainDepth=2,MaxArcs=2,DirectHitChainLength=8,ArcLength=8,ChainDamageMultiplier=.80000001,TimeBetweenAttacks=1)
    if any(p.get(k)!=v for k,v in required.items()):raise ValueError('Grimoire native chain/life signature changed')
    if any(p.get(k,0)!=0 for k in ['ExplodeOnImpact','Embed','MaxLifeVariance']):raise ValueError('Grimoire alternate lifecycle changed')
    for field,amount in [('AttackData',350),('ExplosiveAttack',250)]:
        a=p.get(field) or {}
        if a.get('Type')!='DT_ELECTRICITY' or a.get('Amount')!=amount or a.get('ProcChance')!=.25999999:raise ValueError('Grimoire native packet changed')
    if p.get('CriticalChance')!=.2 or p.get('CriticalMultiplier')!=2:raise ValueError('Grimoire crit changed')
    if p.get('AttackData',{}).get('ForcedProcs')!=['PT_ELECTROCUTION']:raise ValueError('Grimoire contact proc changed')
    mode=w['Behaviors'][1];fire=next(v for k,v in mode.items() if k.startswith('fire:') and isinstance(v,dict))
    if fire.get('IgnoreFireIterations')!=1 or fire.get('fireIterations')!=1:raise ValueError('Grimoire orb-count contract changed')
    evidence=dict(clientSha256=CLIENT_SHA256,packageSha256=PACKAGE_SHA256,nativeSources=source_rows(pkg,[WEAPON,PROJECTILE]),
      classTable='PlayerChainingProjectile0x1423910d0; update+220140239ff0/+230140c02280 ->140d7fc60; Die+5601413556f0 ->1405ac4a0',
      singleOrb='fire IgnoreFireIterations at +0x148 = 1 causes full native 0x140f75d20 to return raw count at +0x28 = 1 without weapon multishot query',
      chainBudgets='140d7fd38..da0 queries weapon+6e0 for MaxTargetsPerAttack3;140d7ff87..d80086 queries same modifier for MaxChainDepth2 and rounds; multishot is not additional orbs',
      cooldown='TimeBetweenAttacks->Projectile+1770; native140d7fcb7..fd06 decrements+1774 then gates new attack;141693034..305c arms+1774 when target-selection phase proceeds',
      perAttackDedup='140d7fd14..33 calls1401bc7d0 to clear+1798 list at each new attack;140ccd260..d32d excludes candidates in that list;1416932a8..2db appends selected target before recursive14169333a',
      chainAmount='140d7fdb4..fde8 builds source AttackData350 via projectile+628;141693108..3123 multiplies copied packet amount by ChainDamageMultiplier+.1768=.80000001 (about280) for selected chain recipient',
      chainRole='141693283 calls140907cb0; packet target handle+170 and projectile source must be native avatars; authoritative target+340 or local target+348 receives current packet;140cc8cd0 separately manages chain visual beam slot',
      expirySchedule='actual projectile+780140f874b0 suffix140f88871..88981 ->140dd80d0 MaxLife6+variance0; ExplodeOnLifeExpired1 selects1409a8700 DieOfOldAge callback, scheduled once by+639',
      expiryEmit='1409a8700 calls class Die first; death callback140163b01 with16d61/c250 suppresses its radial;1409a8730..8785 explicitly emits+7b8 once per invoked expiry callback; common+630 selects ExplosiveAttack250',
      duplicateExpiryCounterfactual='Native Die+c1d guard suppresses a repeated death callback, but manually repeated DieOfOldAge still emits another radial; scheduler once gate is essential',
      crit='140f36187..36198 calls140ede780 after radial selector to copy+combine Projectile+538/+570 CC/CD; plan118/11c are not crit proof',
      limits=list(BOUNDS))
    evidence.update(
      contact='actual PlayerChainingProjectile1423910d0+790=1400bb680, bytesc20000 ret0; contact350 is constructed but not submitted',
      chainQualification='defaultPROJECTILE2;140907cb0 selected-avatar340/348; ordinary source has no790/818/820 and no victim-side259/261',
      sourceTiming='current ordinary damage/elements/status each attack; retain projectile538/570 crit and context caches',
      recipientPolicy='fixed original recipient; explicit eligible window fromlaunch; no successor rebind; optional final expiry distance',
      followthroughEvidence='docs/projectile-qualification-20261030/GRIMOIRE.md')
    contract=dict(nativeSource=PROJECTILE,nativeField='AttackData',sourceKind='grimoire-single-occupant',
      sourceRawAttributesSha256='a384ff36bc51b96972d82f317e6258ff1f7bf52b0f1754b082437cdb979401ac',
      noDirectContact=True,spawnedOrbs=1,sourceAmount=350.,chainDamageMultiplier=.80000001,
      attackIntervalSeconds=1.,lifetimeSeconds=6.,rootRecipientCap=1,
      takesConditionOverload=False,takesColdStackDamage=False,
      sourceUpgradeTiming='current-damage-elements-status-retained-launch-crit',
      settings=dict(strategy='grimoireStrategy',selected='single-occupant',coverage='grimoireCoverageSeconds',
                    coverageDefaultSeconds=3.,coverageRange=[0.,6.],expiryDistance='grimoireExpiryDistance',
                    expiryDistanceRange=[0.,6.],defaultCoverage='off'),
      chain=dict(nativeField='AttackData',nativeRoute='player-chain-selected-avatar',nativeHitType=2,
                 genericHit=True,genericCrit=True,takesVictimCrit=True,forcedProcs=['PT_ELECTROCUTION']),
      expiry=dict(nativeField='ExplosiveAttack',nativeRoute='launch-expiry-region',nativeHitType=4,
                  sourceAmount=250.,radiusMeters=6.,falloff=.80000001,genericHit=True,genericCrit=True,takesVictimCrit=False),
      evidence=evidence)
    return dict(schemaVersion=2,kind='native-grimoire-source-contract',
      weapons={}, sourceContracts={WEAPON:{'1':dict(noDirectContact=True,grimoireSourceContract=contract,unmodeled=list(BOUNDS))}},
      pending=[dict(path=WEAPON,mode=1,
      candidateOnly=True,defaultScoringExcluded=True,reason='optional explicit original-recipient coverage; source contract separately suppresses nonexistent direct contact',
      sourcePayload=dict(contact=dict(damage={'electricity':350.},forcedProcs=['PT_ELECTROCUTION'],damageSubmitted=False),
        chain=dict(sourceAmount=350.,sourceMultiplier=.80000001,nominalAmount=280.,attackIntervalSeconds=1.,directLength=8.,arcLength=8.,
            maxTargets=3,maxDepth=2,maxArcs=2,dedupScope='one target-selection attack, reset next attack',spawnedOrbs=1),
        expiry=dict(damage={'electricity':250.},radius_m=6.,falloff=.80000001,lifetimeSecondsFromLaunch=6.,
            delaySecondsFromImpact=None,recipient='unresolved final projectile location overlap'),critChance=.2,critMultiplier=2.,statusChance=.25999999),
      unmodeled=list(BOUNDS),evidence=evidence)])

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True)
    ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():ap.error('choose a new evidence output')
    if sha256(a.client_exe)!=CLIENT_SHA256:raise ValueError('native EXE changed')
    row=next(r for r in json.loads(a.export.read_bytes())['data'] if r['path']==WEAPON)
    out=build_contract(AuditedPackages(a.packages_bin),row);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8');print('PASS Grimoire source contract; default contact suppressed; periodic/expiry damage requires explicit coverage policy')
if __name__=='__main__':main()
