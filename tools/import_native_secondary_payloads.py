"""Import hash-pinned native secondary payloads with explicit approximation bounds.

Writes a mergeable per-mode patch; never edits production mechanics implicitly.
Native packet amounts/crit/status are retained independently from unresolved
CO, weakpoint, child, clock, and scene-recipient contracts.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from import_companion_projectile_sequences import AuditedPackages, CLIENT_SHA256, PACKAGE_SHA256

BASE='/Lotus/Weapons/'
SPECS=(
 dict(path=BASE+'Corpus/BoardExec/Secondary/CrpBEPlinx/CrpBEPlinxWeapon',mode=1,
      projectile=BASE+'Corpus/BoardExec/Secondary/CrpBEPlinx/CrpBEPlinxAltFireProj',amount=100,
      field='EmbedDeathAttack',damage={'radiation':100.},direct=100.,family='tenet-plinx',delay=.80000001,
      required={'Embed':1,'EmbedTime':[.80000001,.80000001],'DamageRadius':6,'ExplosionFallOff':.40000001},
      bounds=['tenet-plinx-embedded-death-branch-fixed-delay-approximated',
              'tenet-plinx-charge-ammo-damage-scale-neutral-fallback-unverified',
              'tenet-plinx-airborne500-alternative-excluded','tenet-plinx-vortex-damage-context-unverified',
              'tenet-plinx-main-explosion-CO-neutral-fallback-unverified']),
 dict(path=BASE+'Grineer/LongGuns/GrnChemstrikeNox/GrnChemstrikeNoxRiflePlayer',mode=0,
      projectile=BASE+'Grineer/LongGuns/GrnChemstrikeNox/GrnChemstrikeNoxProjectilePvE',amount=30,
      field='EmbedDeathAttack',damage={'toxin':30.},direct=30.,family='nox-player',delay=3.,
      required={'Embed':1,'EmbedTime':[2,4],'DamageRadius':.75},
      bounds=['nox-player-embedded-death-delay2-4s-approximated-by3s',
              'nox-player-script-radius-growth-neutral-fallback-unverified',
              'nox-player-embedded-ticks-and-trigger-payload-unmodeled',
              'nox-player-main-explosion-CO-neutral-fallback-unverified']),
 dict(path=BASE+'Tenno/LongGuns/PrimeScourge/PrimeScourgeWeapon',mode=1,
      projectile=BASE+'Tenno/LongGuns/PrimeScourge/PrimeScourgeChargedProjectile',amount=55,
      damage={'corrosive':55.},direct=300.,family='scourge-prime',delay=0.,
      required={'ExplodeOnImpact':1,'DamageRadius':7,'ExplosionFallOff':.60000002},
      bounds=['scourge-prime-throw-impact-clock-and-contact-coverage-idealized',
              'scourge-prime-script-lifetime-and-embedded-payload-unmodeled',
              'scourge-prime-main-explosion-CO-neutral-fallback-unverified']),
 dict(path=BASE+'Tenno/LongGuns/RevenantShotgun/RevenantShotgun',mode=1,
      projectile=BASE+'Tenno/LongGuns/RevenantShotgun/AltFireClusterProj',amount=73,
      damage={'radiation':73.},direct=15.,family='phantasma',delay=0.,
      required={'ExplodeOnImpact':1,'DamageRadius':4.8000002,'ExplosionFallOff':.5},
      bounds=['phantasma-main-explosion-CO-neutral-fallback-unverified',
              'phantasma-main-explosion-weakpoint-events-neutral-fallback-unverified',
              'phantasma-cluster-child-payload-unmodeled',
              'phantasma-charge-ammo-scale-and-contact-routing-approximated']),
 dict(path=BASE+'Tenno/LongGuns/PrimePhantasma/PhantasmaPrimeShotgun',mode=1,
      projectile=BASE+'Tenno/LongGuns/PrimePhantasma/PrimeAltFireClusterProj',amount=73,
      damage={'radiation':73.},direct=15.,family='phantasma',delay=0.,
      required={'ExplodeOnImpact':1,'DamageRadius':4.8000002,'ExplosionFallOff':.5},
      bounds=['phantasma-main-explosion-CO-neutral-fallback-unverified',
              'phantasma-main-explosion-weakpoint-events-neutral-fallback-unverified',
              'phantasma-cluster-child-payload-unmodeled',
              'phantasma-charge-ammo-scale-and-contact-routing-approximated']),
 dict(path=BASE+'Lasria/LasGooPistol/LasGooPistolPlayerWeapon',mode=1,
      projectile=BASE+'Lasria/LasGooPistol/LasGooPistolAltFire/LasrianGooPistolPlayerAltFireProjectileFullcharge',
      amount=313,damage={'corrosive':313.},direct=35.,family='efv8',delay=0.,
      required={'ExplodeOnImpact':1,'DamageRadius':3,'ExplosionFallOff':.80000001,'Embed':0},
      bounds=['efv8-main-explosion-CO-neutral-fallback-unverified','efv8-release-flight-and-recipient-coverage-idealized']),
 dict(path=BASE+'Tenno/Archwing/Primary/TnShieldframeArchGun/TnShieldFrameArchGun',mode=1,
      projectile=BASE+'Tenno/Archwing/Primary/TnShieldframeArchGun/TnShieldFrameHeavyArchgunProjectile',
      amount=1600,damage={'blast':800.,'radiation':800.},direct=840.,family='larkspur',delay=1.,
      required={'DamageRadius':9.6000004,'ExplosionFallOff':.60000002,'MaxLife':1,'DestroyOnStaticCollision':1,'AllowNormalContactBehavior':1},
      bounds=['larkspur-main-explosion-contact-versus-expiry-clock-approximated-1s',
              'larkspur-expiry-explosion-target-overlap-idealized','larkspur-main-explosion-CO-neutral-fallback-unverified']),
 dict(path=BASE+'Tenno/Archwing/Primary/PrimeLarkspur/PrimeLarkspurWeapon',mode=1,
      projectile=BASE+'Tenno/Archwing/Primary/PrimeLarkspur/PrimeLarkspurHeavyProjectile',
      amount=1600,damage={'blast':800.,'radiation':800.},direct=840.,family='larkspur',delay=1.,
      required={'DamageRadius':9.6000004,'ExplosionFallOff':.60000002,'MaxLife':1,'DestroyOnStaticCollision':1,'AllowNormalContactBehavior':1},
      bounds=['larkspur-main-explosion-contact-versus-expiry-clock-approximated-1s',
              'larkspur-expiry-explosion-target-overlap-idealized','larkspur-main-explosion-CO-neutral-fallback-unverified']),
 dict(path=BASE+'Tenno/LongGuns/SapientPrimary/SapientPrimaryWeapon',mode=0,
      projectile=BASE+'Tenno/LongGuns/SapientPrimary/SapientPrimaryProjectile',
      amount=44,damage={'puncture':35.20000044,'slash':8.79999956},direct=26.,export_direct_totals=(26.,35.),family='acceltra',delay=0.,
      required={'DamageRadius':4,'ExplosionFallOff':.5,'ArmingDistance':6,'SkipHitEffectWhenArmed':1},
      bounds=['acceltra-arming-distance-default-assumed-armed',
              'acceltra-main-explosion-CO-neutral-fallback-unverified','acceltra-main-explosion-weakpoint-events-neutral-fallback-unverified',
              'acceltra-contact-death-timing-and-target-centre-coverage-idealized','acceltra-embedded-alternative-payload-excluded']),
 dict(path=BASE+'Tenno/LongGuns/PrimeAcceltra/PrimeAcceltraWeapon',mode=0,
      projectile=BASE+'Tenno/LongGuns/PrimeAcceltra/PrimeAcceltraProjectile',amount=53,
      damage={'puncture':42.40000053,'slash':10.59999947},direct=44.,direct_status=.18000001,
      export_direct_totals=(44.,),family='acceltra',delay=0.,
      required={'DamageRadius':5,'ExplosionFallOff':.5,'ArmingDistance':6,'SkipHitEffectWhenArmed':1},
      bounds=['acceltra-arming-distance-default-assumed-armed',
              'acceltra-contact-death-timing-and-target-centre-coverage-idealized','acceltra-embedded-alternative-payload-excluded']),
 dict(path=BASE+'Tenno/Grimoire/TnGrimoire',mode=1,
      projectile=BASE+'Tenno/Grimoire/TnGrimoireAltProj',amount=250,
      damage={'electricity':250.},direct=350.,family='grimoire',delay=6.,
      required={'ExplodeOnLifeExpired':1,'MaxLife':6,'DamageRadius':6,'ExplosionFallOff':.80000001},
      bounds=['grimoire-alt-expiry-explosion-recipient-overlap-idealized',
              'grimoire-alt-contact-bounce-expiry-clock-approximated-6s',
              'grimoire-alt-chains-and-repeat-contact-payload-unmodeled',
              'grimoire-alt-main-explosion-CO-neutral-fallback-unverified']),
)


ADMITTED_FAMILIES=frozenset({'phantasma','efv8'})
ADMITTED_SPECS=tuple(spec for spec in SPECS if spec['family'] in ADMITTED_FAMILIES)
PENDING_REASONS={
    'tenet-plinx':'EmbedDeath100 versus airborne500 death branch and ammo-scale consumer not closed',
    'nox-player':'script radius/embedded death clock and tick-versus-death dispatch not closed',
    'scourge-prime':'Javelin impact versus scripted-embed contact callback branch not closed',
    'larkspur':'Wave static-contact/expiry death activation and event origin time not closed; MaxLife is not impact delay',
    'acceltra':'native arming/death/source closure complete; incremental v4 requires --only-family acceltra and removal of stale wiki35 override',
    'grimoire':'MaxLife6 is launch lifetime rather than impact delay; expiry recipient and repeat-chain/contact clock not closed',
}


def sha256(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def ancestry(pkg,path):
    rows=[];seen=set()
    while path and path not in seen:
        rows.append(path);seen.add(path);path=pkg.parent(path)
    if path:raise ValueError('native parent cycle: '+path)
    return rows


def source_rows(pkg,paths):
    rows=[]
    for path in dict.fromkeys(a for path in paths for a in ancestry(pkg,path)):
        entity=pkg.entities[path][1]
        raw=pkg._reader.decompress(entity) if entity.attr is not None else b''
        rows.append(dict(path=path,parent=pkg.parent(path),rawAttributesSha256=hashlib.sha256(raw).hexdigest(),
                         attributeRecord=entity.attr is not None))
    return rows


def _resolve_ref(pkg,owner,ref):
    if not ref:return None
    return pkg.locate(owner,ref)


def profile(pkg,row,spec):
    path=spec['path'];ordinal=spec['mode'];modes=row.get('fireModes') or []
    if row.get('path')!=path or len(modes)<=ordinal:raise ValueError('export weapon/mode identity changed: '+path)
    mode=modes[ordinal];damage=mode.get('damage') or {};projectile=spec['projectile']
    if damage.get('projectile')!=projectile or all(abs(sum((damage.get('types') or {}).values())-value)>.02 for value in spec.get('export_direct_totals',(spec['direct'],))):
        raise ValueError('export direct/projectile identity changed: '+path)
    raw=pkg.resolve(path)
    bank=row.get('fireModeSource') or ('HeavyBehaviors' if row.get('slot')=='arch_gun' and raw.get('HeavyBehaviors') else 'Behaviors')
    native_index=mode.get('index',ordinal);behaviors=raw.get(bank) or []
    if not isinstance(native_index,int) or isinstance(native_index,bool) or not 0<=native_index<len(behaviors):raise ValueError('native behavior identity changed')
    behavior=behaviors[native_index]
    fire=next((v for k,v in behavior.items() if k.startswith('fire:') and isinstance(v,dict)),{})
    state=next((v for k,v in behavior.items() if k.startswith('state:') and isinstance(v,dict)),{})
    if fire.get('fireIterations')!=1 or mode.get('multishot')!=1:raise ValueError('not the audited one-projectile base emission')
    primary_ref=fire.get('chargedProjectileType') if mode.get('chargedProjectile') else fire.get('projectileType')
    if _resolve_ref(pkg,path,primary_ref)!=projectile:raise ValueError('native selected projectile changed')
    p=pkg.resolve(projectile);native_field=spec.get('field','ExplosiveAttack');attack=p.get(native_field) or {}
    if attack.get('Amount')!=spec['amount'] or any(p.get(k)!=v for k,v in spec['required'].items()):
        raise ValueError('native explosion contract changed: '+projectile)
    dtype={'radiation':'DT_RADIATION','corrosive':'DT_CORROSIVE','electricity':'DT_ELECTRICITY','blast':'DT_EXPLOSION','puncture':'DT_PUNCTURE','slash':'DT_SLASH','toxin':'DT_POISON'}
    if attack.get('UseNewFormat'):
        vector={k:float(v) for k,v in attack.items() if k.startswith('DT_') and float(v)}
        expected={dtype[k]:v for k,v in spec['damage'].items()}
        if vector!=expected:raise ValueError('native per-type explosion split changed')
    elif attack.get('Type')=='DT_PHYSICAL':
        for k,v in spec['damage'].items():
            if abs(float(attack.get(dtype[k],0))*spec['amount']-v)>1e-5:raise ValueError('native physical split changed')
    elif attack.get('Type')!=dtype[next(iter(spec['damage']))] or len(spec['damage'])!=1:
        raise ValueError('native explosion type changed')
    for key in ['CriticalChance','CriticalMultiplier']:
        if not isinstance(p.get(key),(int,float)):raise ValueError('native crit missing: '+key)
    if not isinstance(attack.get('ProcChance'),(int,float)):raise ValueError('native explosion status missing')
    copies=[]
    for key in ('MultiShotProjectileType','MultiShotChargedProjectileType'):
        ref=fire.get(key)
        if ref:
            copy_path=_resolve_ref(pkg,path,ref)
            if not copy_path:raise ValueError('unresolved multishot projectile')
            copy=pkg.resolve(copy_path)
            for key in [native_field,'CriticalChance','CriticalMultiplier','DamageRadius','ExplosionFallOff']:
                if copy.get(key)!=p.get(key):raise ValueError('multishot-copy explosion differs: '+copy_path)
            copies.append(copy_path)
    component=dict(damage=deepcopy(spec['damage']),radius_m=float(p['DamageRadius']),falloff_start_m=0.,
        falloff_reduction=float(p.get('ExplosionFallOff',0.)),crit_chance=float(p['CriticalChance']),
        crit_multiplier=float(p['CriticalMultiplier']),status_chance=float(attack['ProcChance']),
        forcedProcs=list(attack.get('ForcedProcs') or []),takes_multishot=True,takes_blast_radius_mods=True,
        takes_condition_overload=False,impact_delay_seconds=spec['delay'],nativeSource=projectile,nativeField=native_field,
        sourceHitType=attack.get('HitType','DHT_RADIAL'),declaredHitType=attack.get('HitType'),
        hitTypeSource='native-explicit' if attack.get('HitType') else 'native-none-filled-radial-by-0x14123499a',
        damageTypeSource='native-explicit',
        emissionContract=dict(baseFireIterations=1,baseExportMultishot=1,packetsPerSpawnedProjectile=1,
            amountAlreadyIncludesProjectileCount=False,multishotCopyProjectiles=copies,
            consumer='0x140f360f0 -> +0x630 / 0x14160c5a0 -> +0x638 / 0x141234720'),
        approximation=dict(conditionOverload='neutral-pending-specific-routing',headDamageBonus='suppressed',
            weakpointCriticalAndKillEvents='neutral-pending-proof',recipient='target at explosion centre assumed',
            flightAndCollisionTiming='impact-immediate' if spec['delay']==0 else 'native-MaxLife-as-fixed-delay'))
    if spec['family']=='acceltra':
        direct=p.get('AttackData') or {}
        if direct.get('Amount')!=spec['direct'] or direct.get('Type')!='DT_IMPACT' or direct.get('ProcChance')!=spec.get('direct_status',.059999999):
            raise ValueError('Acceltra native direct packet changed')
        if p.get('ExplodeOnImpact',0)!=0 or p.get('ExplodeOnLifeExpired',0)!=0 or p.get('Embed',0)!=0:
            raise ValueError('Acceltra constructor death/embedded route changed')
        # Both constructor bits are explicitly zero (0x140fbb19e/0x140fbb1af).
        component['armingDistance']=float(p['ArmingDistance'])
        component['emissionContract']['consumer']='0x1410e3b5d Die -> Projectile death callback0x140163a60 -> +0x7b8/0x140f360f0; normal c25=0 selects ExplosiveAttack'
        component['activationEvidence']={'armingMember':'Projectile+0x158c',
            'compare':'0x140163ac7..0x140163afb euclidean displacement >= 6',
            'deathGate':'0x140163b01..0x140163b34 zero ExplodeOnImpact/ExplodeOnLifeExpired -> one +0x7b8 call',
            'embedDisabled':'mEmbed+0x8e0 constructor0; no source override; c25 normal0',
            'impactDirect':'0x1410e2bba source Projectile+0x4d0 -> +0x628/0x1416373e0',
            'timing':'contact death; flight and first bounce path idealized by existing single-target impact contract'}
        component['approximation']['flightAndCollisionTiming']='contact-death treated immediate; native launch lifetime not converted to post-hit delay'
    if native_field=='EmbedDeathAttack':component['exclusiveAlternatives']=['ExplosiveAttack']
    if spec['family']=='nox-player':component['falloffSource']='native-constructor0; Projectile+0x634 within zeroed+0x630 qword'
    if spec['family']=='tenet-plinx':component['approximation']['chargeDamageScale']='neutral1 pending ammo/clip consumer; no double-count of alternative500'
    from import_projectile_components import apply_native_contract
    apply_native_contract(component)
    if spec['family']=='phantasma':
        if attack.get('HitType')!='DHT_PROJECTILE':raise ValueError('Phantasma explicit hit type changed')
        component['hitTypeSource']='native-explicit-preserved-by-0x141234988..0x1412349aa'
        component['headSuppressionSource']='0x140bc29fc victimPacket+0x25c=1; independent of hitType'
        component['takes_victim_crit']=True
        component['victimCritEvidence']='ordinary weapon source; victim1408ea3d0 HitType mask0x0e and source predicate141baa200(arg1)'

    profile=dict(name=row.get('nameEn'),directTotal=spec['direct'],fireMode=ordinal,projectile=projectile,
        scope='bounded single-target parent explosion; declared per spawned projectile; unresolved gates approximated explicitly',
        radials=[component],unmodeled=list(spec['bounds']),behaviourSource=f'{bank}[{native_index}]',
        nativeSources=source_rows(pkg,[path,projectile,*copies]),packageBuild='2026.10.22.13.12',packageSha256=PACKAGE_SHA256,
        generatedBy='tools/import_native_secondary_payloads.py',nativeEvidence=dict(clientSha256=CLIENT_SHA256,
            packetCopy='0x140508e9e..0x140508eea',radiusPlan='0x14160c618..0x14160c680',
            parentAmountScale='0x141234a7a',statusNormalization='0x1412353ef raw fireIterations / 0x141586f50',
            critFields='Projectile.CriticalChance/CriticalMultiplier +0x538/+0x570; death path0x140f36198 ->0x140ede780 copies modifier buckets into radial plan, adding existing plan CC and multiplying existing plan CD'))
    if spec['family'] in ('phantasma','efv8','larkspur','acceltra'):
        if p.get('DamageUpgradeTypes',['WEAPON_DAMAGE_AMOUNT'])!=['WEAPON_DAMAGE_AMOUNT']:
            raise ValueError('main explosion damage upgrade route changed')
        component['approximation']['conditionOverload']='native-excluded for ordinary weapon source without Powersuit/ability parent'
        component['approximation']['weakpointCriticalAndKillEvents']='selected body geometry; native head/weakpoint events depend on independently rebuilt hit proxy'
        component['conditionOverloadEvidence']='common +7b8 bypasses contact +818/+820; victim +758/14111fa60 requires 141baa200(arg0), false for ordinary unparented gun'
        profile['unmodeled']=[note for note in profile['unmodeled'] if note not in (
            spec['family']+'-main-explosion-CO-neutral-fallback-unverified',
            spec['family']+'-main-explosion-weakpoint-events-neutral-fallback-unverified')]
        profile['unmodeled'].append(spec['family']+'-main-explosion-proxy-geometry-body-policy')
    if spec['family']=='acceltra':
        sequence=[_resolve_ref(pkg,path,ref) for ref in fire.get('projectileSequenceList') or []]
        for copy_path in sequence:
            if not copy_path:raise ValueError('unresolved Acceltra cosmetic projectile')
            copy=pkg.resolve(copy_path)
            for key in ['AttackData','ExplosiveAttack','CriticalChance','CriticalMultiplier','DamageRadius','ExplosionFallOff','ArmingDistance','SkipHitEffectWhenArmed']:
                if copy.get(key)!=p.get(key):raise ValueError('Acceltra cosmetic payload differs: '+copy_path)
        profile['nativeSources']=source_rows(pkg,[path,projectile,*copies,*sequence])
        profile['nativeDirectCorrection']=dict(damageTypes={'DT_IMPACT':spec['direct']},procChance=spec.get('direct_status',.059999999),
            reason='exact current native AttackData; base Acceltra historical wiki35 override must remain removed',
            source=projectile,nativeField='AttackData',acceptedPriorExportTotals=list(spec['export_direct_totals']))
    if state.get('ChargeTime') is not None:
        profile['charge']=dict(seconds=float(state['ChargeTime']),modifier=state.get('ChargeModifier'),
            scalesWithFireRate=state.get('ChargeModifier')=='WEAPON_FIRE_RATE',source='native-ChargeTime',
            nativeSource=path,nativeField=f'{bank}[{native_index}].state.ChargeTime')
    if spec['family']=='phantasma':
        profile.pop('charge', None)
        profile.update(phantasma_lifecycle(pkg, path, projectile))
        profile['unmodeled'] = [note for note in profile['unmodeled'] if note not in (
            'phantasma-cluster-child-payload-unmodeled', 'phantasma-charge-ammo-scale-and-contact-routing-approximated')]
        profile['unmodeled'].append('phantasma-child-body-geometry-and-flight-policy-explicit')
    return profile


def phantasma_lifecycle(pkg, path, projectile):
    """Native full-clip charge plus opt-in, explicitly ideal child overlap."""
    mode = pkg.resolve(path)['Behaviors'][1]
    state = mode['state:WeaponChargedStateBehavior']
    fire = mode['fire:LotusWeaponProjectileFireBehavior']
    required = dict(ClipSizeAffectsChargeTime=1, UseClipSizeAsDamageMultiplier=1,
                    UseClipWhileCharging=1, MinChargeRatio=1, AutoFireWhenChargeCompleted=1)
    if any(state.get(k) != v for k, v in required.items()) or state['ChargeTime'] != .090899996:
        raise ValueError('Phantasma charged-state source changed')
    if fire.get('AttenuateForCharge') != 1 or fire.get('AttenuateFireIterationsForCharge') != 0:
        raise ValueError('Phantasma charge routing changed')
    extra_carrier = _resolve_ref(pkg, path, fire['MultiShotProjectileType'])
    lanes = {}
    for kind, owner, count, amounts in [('normal-parent', projectile, 5, (3, 18)),
                                         ('extra-ms-parent', extra_carrier, 2, (6, 36))]:
        source = pkg.resolve(owner)
        if source.get('ClusterApplyDamageMultiplier') != 1 or source.get('NumClusterProjectiles', 5) != count:
            raise ValueError('Phantasma child generation changed')
        child_path = _resolve_ref(pkg, owner, source['ClusterProjectiles'])
        child = pkg.resolve(child_path)
        packets = []
        for field, amount in zip(('AttackData', 'ExplosiveAttack'), amounts):
            attack = child[field]
            if attack['Amount'] != amount:
                raise ValueError('Phantasma child template changed')
            packets.append(dict(damage={attack['Type']: float(amount)}, takes_multishot=False,
                takes_condition_overload=False,
                crit_chance=float(child['CriticalChance']), crit_multiplier=float(child['CriticalMultiplier']),
                status_chance=float(attack['ProcChance']), forcedProcs=list(attack.get('ForcedProcs') or ()),
                nativeSource=child_path, nativeField=field,
                approximation=dict(recipient='explicit ideal-contact policy only',
                    arrival='configured arrival assumption, not native expiry',
                    qualification='body damage; CO and modifier/event consumers remain independently bounded')))
            from import_projectile_components import apply_native_contract
            apply_native_contract(packets[-1])
        lanes[kind] = dict(count=count, nativeCarrier=owner, packets=packets)
    return dict(fullClipCharge=dict(cadencePolicy='ordinary-reload-full-clip',
                    chargeSecondsPerRound=float(state['ChargeTime']), nativeSource=path,
                    nativeField='Behaviors[1].state:WeaponChargedStateBehavior',
                    parentScale='captured loaded rounds; native projectile+7b8',
                    childScale='independent ClusterApplyDamageMultiplier snapshot+1738, default1'),
                phantasmaChildren=dict(idealArrivalSeconds=.7, defaultOverlapPolicy='off',
                    lifetimeRangeSeconds=[2.2, 2.9], **lanes))


def row_name(row):
    return row.get('nameEn') or row.get('name')


def build_patch(pkg,rows,*,families=None):
    by={row['path']:row for row in rows}
    if len(by)!=len(rows):raise ValueError('duplicate export weapon path')
    admitted=ADMITTED_FAMILIES if families is None else frozenset(families)
    if admitted-set(s['family'] for s in SPECS):raise ValueError('unknown admitted family')
    if admitted-ADMITTED_FAMILIES-{'acceltra'}:raise ValueError('family still pending native closure')
    result={};pending=[];previously_admitted=[]
    for spec in SPECS:
        entry=profile(pkg,by[spec['path']],spec)
        if spec['family'] in admitted:
            result.setdefault(spec['path'],{})[str(spec['mode'])]=entry
        elif spec['family'] in ADMITTED_FAMILIES:
            previously_admitted.append(dict(path=spec['path'],mode=spec['mode'],reason='already admitted separately; excluded from incremental patch'))
        else:
            pending.append(dict(path=spec['path'],mode=spec['mode'],name=row_name(by[spec['path']]),
                reason=PENDING_REASONS.get(spec['family'],'already admitted separately; excluded from this incremental patch'),
                candidateOnly=True,defaultScoringExcluded=True,sourcePayload=entry))
    return dict(schemaVersion=1,kind='auditedAttacks-mode-merge',packageSha256=PACKAGE_SHA256,
                clientSha256=CLIENT_SHA256,weapons=result,pending=pending,previouslyAdmittedExcluded=previously_admitted,
                interpretation='Only weapons entries are admitted. Pending sourcePayload records are evidence-only and excluded from merge/scoring.')


def merge_patch(payload,patch):
    """Return a copy; preserve unrelated root fields and all other modes."""
    result=deepcopy(payload)
    for path,modes in patch['weapons'].items():
        root=result.setdefault('auditedAttacks',{}).setdefault(path,{})
        for index,entry in modes.items():
            target=root if index=='0' else root.setdefault('modes',{}).setdefault(index,{})
            incoming=deepcopy(entry)
            if 'unmodeled' in incoming:
                retired={'phantasma-parent-explosion-and-children-unmodeled',
                         'phantasma-explosion-co-and-head-event-routing-unverified'} if 'Phantasma' in path or 'RevenantShotgun' in path else set()
                for spec in SPECS:
                    if spec['path']==path and spec['family'] in ('phantasma','efv8','larkspur','acceltra') and any(
                            part.get('conditionOverloadEvidence') and part.get('nativeSource')==spec['projectile']
                            for part in incoming.get('radials',())):
                        retired.update({spec['family']+'-main-explosion-CO-neutral-fallback-unverified',
                                        spec['family']+'-main-explosion-weakpoint-events-neutral-fallback-unverified'})
                if incoming.get('attachedTicks') and incoming.get('nativeSpearThrowCycle'):
                    retired.update({'scourge-prime-main55-CO-weakpoint-events-neutral-fallback-unverified',
                                    'scourge-prime-stopped-embedded-script-payload-unmodeled',
                                    'scourge-prime-old-spear-deferred-die-and-embedded-damage-excluded',
                                    'scourge-prime-script-lifetime-and-embedded-payload-unmodeled'})
                incoming['unmodeled']=list(dict.fromkeys(
                    warning for warning in [*(target.get('unmodeled') or []),*incoming['unmodeled']]
                    if warning not in retired))
            if index=='0':
                old_modes=deepcopy(root.get('modes',{}));root.update(incoming)
                if old_modes:root['modes']=old_modes
            else:target.update(incoming)
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True)
    ap.add_argument('--exports',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--only-family',action='append',choices=sorted(ADMITTED_FAMILIES|{'acceltra'}),help='emit only these proven families; use acceltra for incremental v4 without overwriting v3')
    a=ap.parse_args(argv)
    if a.output.exists():ap.error('preserve evidence: output already exists')
    if sha256(a.client_exe)!=CLIENT_SHA256:raise ValueError('client changed; repeat native consumer audit')
    pkg=AuditedPackages(a.packages_bin);pkg.own=lru_cache(maxsize=None)(pkg.own)
    rows=json.loads(a.exports.read_text(encoding='utf-8-sig'))
    if isinstance(rows,dict):rows=rows.get('weapons',rows.get('data'))
    patch=build_patch(pkg,rows,families=a.only_family);patch['inputs']={k:dict(path=str(v.resolve()),sha256=sha256(v)) for k,v in [('packages',a.packages_bin),('client',a.client_exe),('exports',a.exports)]}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf8') as f:json.dump(patch,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(dict(weapons=len(patch['weapons']),modes=sum(len(m) for m in patch['weapons'].values()),pendingModes=len(patch['pending']),output=str(a.output)),ensure_ascii=False))


if __name__=='__main__':main()
