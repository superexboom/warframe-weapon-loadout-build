"""Retain the Nox player-prototype script contract without inventing a damage clock.

The resource reuses Grakata's display label. Exact internal paths distinguish it
from ordinary Grakata; MarketMode alone does not prove player availability.
"""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
from copy import deepcopy
from tools.import_native_secondary_payloads import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,source_rows,sha256
from tools.refresh_spread_talons import preserve_lines
ROOT=Path(__file__).resolve().parents[1]
WEAPON='/Lotus/Weapons/Grineer/LongGuns/GrnChemstrikeNox/GrnChemstrikeNoxRiflePlayer'
PROJECTILE='/Lotus/Weapons/Grineer/LongGuns/GrnChemstrikeNox/GrnChemstrikeNoxProjectilePvE'
TRIGGER='/Lotus/Types/Enemies/Grineer/ChemStrike/NoxGooTrigger'
SCRIPT='/Lotus/Scripts/WeaponAttachments/NoxWeapon.lua'
SCRIPT_SHA='3129454e35dcde6980d5773201f0f0cd3ce65f21dff1eaa2d22e5becf77a6129'
WARNINGS=['nox-player-embed-tick-and-death-clock-unmodeled','nox-player-overlap-script-can-terminate-owner-unverified','nox-player-source-and-event-routing-unverified']


def audit(pkg):
    p=pkg.resolve(PROJECTILE);t=pkg.resolve(TRIGGER);w=pkg.resolve(WEAPON)
    if (p.get('Embed')!=1 or p.get('EmbedTime')!=[2,4] or p.get('DamageRadius')!=.75
            or p.get('EmbedDamageRadius',0)!=0 or p.get('AttackData',{}).get('Amount')!=30 or p.get('EmbedAttack',{}).get('Amount')!=3
            or p.get('EmbedDeathAttack',{}).get('Amount')!=30 or p.get('EmbedDeathAttack',{}).get('HitType')!='DHT_PROJECTILE'):
        raise ValueError('Nox prototype damage/lifecycle changed')
    stop=p.get('OnProjectileStoppedScript') or {}
    if (stop.get('Script')!=SCRIPT or stop.get('Function')!='OnStop'
            or stop.get('_growthTriggerType')!=TRIGGER or stop.get('_projectileDamageRadius')!=1.5):
        raise ValueError('Nox stopped callback changed')
    if (t.get('PhysicsBehavior')!='/EE/Types/Physics/KinematicTrigger' or t.get('Radius')!=1.5
            or t.get('AttackData') or len(t.get('Scripts') or [])!=1):
        raise ValueError('Nox overlap trigger is not the audited nondamaging trigger')
    callback=t['Scripts'][0].get('Script') or {}
    if callback.get('Script')!=SCRIPT or callback.get('Function')!='OnOverlap':raise ValueError('Nox overlap callback changed')
    return dict(status='source-closed-stable-avatar-profile-implemented',clientSha256=CLIENT_SHA256,
        packagesSha256=PACKAGE_SHA256,script=SCRIPT,scriptSha256=SCRIPT_SHA,nativeSources=source_rows(pkg,[WEAPON,PROJECTILE,TRIGGER]),
        displayIdentity=dict(path=WEAPON,localizeTag=w.get('LocalizeTag'),marketMode=w.get('MarketMode'),availability='not-established-from-MarketMode'),
        nonDamageTrigger=dict(path=TRIGGER,hasAttackData=False,behavior='OnOverlap obtains parent and requests parent death; not another damage field'),
        declaredPayloads=dict(contact=deepcopy(p['AttackData']),embeddedTick=deepcopy(p['EmbedAttack']),embeddedDeath=deepcopy(p['EmbedDeathAttack']),embedTimeRange=[2,4]),
        consumers=dict(radius='OnStop P0pc131..135 Lua atomf6e051dd ->0x141981f90 writesProjectile+63c using script1.5; subsequent visualScale setter is independent',
            overlap='OnOverlap P2pc0..11 atom557c9672 ->0x14196cbb0 readsEntity+3a0;atom9c6a9ac9 ->0x14196e520 callsparent+418 death',
            branch='OnStop first branch tests Avatar* atom0xae46e6de: descriptor1427a6cc0 ->registration1427aef50; living Avatar host enters slow loop and returns before terrain growth trigger',
            bytecode='current VM table14192ee08 raw00 ->handler14192e471: interrupt-aware signedD JUMPBACK; Nox body zero unknown opcodes and zero invalid jumps',
            timing='base142101120 slots738/418: immediate tick then1s; natural2..4s EmbeddedDie request; actualDie deferred.075..15s; early host/status/weapon changes request418 death'),
        avatarBranch=dict(type='Avatar',typeAtom='0xae46e6de',typeDescriptor='0x1427a6cc0',registration='0x1427aef50',
            liveHostRadius=float(p['DamageRadius']),createsGrowthTrigger=False,
            scope='valid living Avatar host at OnStop; host/status/weapon changes may request early death'),
        stableAvatarTickContract=dict(nativeSource=PROJECTILE,nativeField='EmbedAttack',nativeRoute='attached-target',
            damage={'toxin':3.},statusChance=0.,tickRate=1.,firstTickDelaySeconds=0.,
            embedDamageRadius=0.,radiusSource='ctor140fbaa7b zero960; serializer140da1f88 mEmbedDamageRadius; no source override',
            damageHitType=7,damageHitTypeName='DHT_DOT',takesConditionOverload=False,
            takesVictimStackDamage=False,takesVictimCrit=False,genericHit=True,genericCriticalHit=True,
            recipient='original attached live Avatar only',
            consumer='140a58cb0 zero960 branch140a58dcd ->628 caller7 at140a58ea1 ->victim340 at140a58f2d; bypasses790/818',
            lifetimePolicy='uniform2..4 natural request, cancel future ticks at request; mean3 is an explicit representative, not exact expected tick count',
            eventPolicy='host340 ->authority AGC accepts DOT7 generic hit/crit; no head bonus or victim crit from type7'),
        stableAvatarProfile=dict(policy='stable-living-avatar-host-uniform-expiry',
            assumptions=['accepted contact embeds into original living Avatar','owner/host/status/weapon remain valid until natural expiry',
                'original host remains inside death radius at explosion; no replacement-target delivery'],
            attachedTicks=dict(damage={'toxin':3.},status_chance=0.,crit_chance=.15000001,crit_multiplier=1.5,
                nativeSource=PROJECTILE,nativeField='EmbedAttack',nativeRoute='attached-target',nativeHitType=7,
                takes_condition_overload=False,takes_victim_stack_damage=False,takes_victim_crit=False,
                coProfile=dict(behavior='none'),typedFlatDamage=False,liveSourceDamageAtTick=True,
                retainsLaunchCrit=True,takes_multishot=True,tick_rate=1.,duration_seconds=3.,
                tickAgesSeconds=[0.,1.,2.,3.],tickSurvivalWeights=[1.,1.,1.,.5],expectedTicksPerProjectile=3.5,
                recipientPolicy='original-attached-host',initial_tick=True,endpointPolicy='uniform-expiry-survival-weighted'),
            radial=dict(damage={'toxin':30.},status_chance=.25,crit_chance=.15000001,crit_multiplier=1.5,
                nativeSource=PROJECTILE,nativeField='EmbedDeathAttack',nativeRoute='delayed-embed-explosion',
                nativeHitType=2,impact_delay_seconds=3.1125,radius_m=.75,falloff_start_m=0.,falloff_reduction=0.,
                takes_condition_overload=False,takes_victim_stack_damage=False,takes_victim_crit=True,takes_multishot=True,
                coProfile=dict(behavior='none'),recipientPolicy='original-host-centre-at-death'),
            unmodeled=['nox-stable-avatar-host-status-weapon-continuity-assumed',
                'nox-natural-expiry-and-death-delay-represented-by-mean3.1125',
                'nox-uniform-tick-survival-weights-ignore-frame-jitter-and-cross-packet-correlation',
                'nox-death-original-host-centre-coverage-idealized']),
        evidence='docs/mechanics-followthrough-20261102/SCRIPT-PAYLOADS.md',
        unresolved=['terrain-trigger-overlap-recipients','avatar-host-status-and-weapon-change-early-death-outside-selected-policy','frame-jitter-and-expiry-tick-correlation'],
        interpretation='Selected stable living Avatar profile separates original-host DOT7 ticks from death30 projectile radial; runtime implements survival weights and stated policy with explicit mean-death/frame-correlation bounds')


def merge(reference,evidence):
    result=deepcopy(reference);entry=result.setdefault('auditedAttacks',{}).setdefault(WEAPON,{})
    entry['noxScriptAudit']=deepcopy(evidence)
    policy=evidence.get('stableAvatarProfile')
    if evidence.get('status')=='source-closed-stable-avatar-profile-implemented' and policy:
        entry['noxAvatarLifecycle']=deepcopy(policy)
        entry['unmodeled']=list(dict.fromkeys([*(v for v in entry.get('unmodeled',[]) if v not in WARNINGS),*policy['unmodeled']]))
    else:
        entry['unmodeled']=list(dict.fromkeys([*(entry.get('unmodeled') or []),*WARNINGS]))
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True);ap.add_argument('--script-body',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--apply-to',type=Path);a=ap.parse_args()
    if a.output.exists():ap.error('preserve evidence; choose new output')
    if sha256(a.client_exe)!=CLIENT_SHA256 or sha256(a.script_body)!=SCRIPT_SHA:raise ValueError('source identity changed')
    result=audit(AuditedPackages(a.packages_bin))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    if a.apply_to:
        original=a.apply_to.read_bytes();a.apply_to.write_bytes(preserve_lines(original,(json.dumps(merge(json.loads(original),result),ensure_ascii=False,indent=2)+'\n').encode('utf8')))
    print('Nox exact-path audit: stable Avatar ticks/death contract; terrain overlap remains separate')


if __name__=='__main__':main()
