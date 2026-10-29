"""Native Mutalist Cernos independent swarm field with source-owner lifecycle.

The 5-damage arrow EmbedAttack is independent. The extra 3-damage trigger has
its own 0.5-second clock and weapon-parent upgrade context. A scorer keeps one field per source weapon, expiring with its arrow owner.
Centered-target coverage follows the enclosing attack model; multishot must not
create independent concurrent fields.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from import_companion_projectile_sequences import AuditedPackages, CLIENT_SHA256, PACKAGE_SHA256
WEAPON='/Lotus/Weapons/Infested/Bow/InfCernosBow/InfCernos'
PROJECTILE='/Lotus/Weapons/Infested/Bow/InfCernosBow/ChargeInfCernosArrowProjectile'
EMBED='/Lotus/Fx/Weapons/Infested/Cernos/InfCernosEmbed'
TRIGGER='/Lotus/Weapons/Infested/Bow/InfCernosBow/InfCernosSwarmDamageTrigger'
SCRIPT='/Lotus/Scripts/WeaponAttachments/InfCernos.lua'
SCRIPT_SHA256='869c8fe4e1acba195c9703e63fa5aa8d0314e770ba04589f125240f825249666'
UNMODELED=['mutalist-cernos-swarm-first-update-versus-enter-phase-unmodeled',
 'mutalist-cernos-swarm-shared-weapon-replacement-ms-order-unverified',
 'mutalist-cernos-swarm-special-source-upgrades-unmodeled',
 'mutalist-cernos-swarm-status-kill-arcane-dispatch-unverified']


def profile(packages,row):
    modes=row.get('fireModes') or []
    if (row.get('path')!=WEAPON or len(modes)!=1
        or modes[0].get('damage',{}).get('projectile')!=PROJECTILE
        or abs(sum(modes[0]['damage']['types'].values())-410)>1e-4):
        raise ValueError('Mutalist Cernos charged export identity changed')
    projectile=packages.resolve(PROJECTILE);embed=packages.resolve(EMBED);trigger=packages.resolve(TRIGGER)
    weapon=packages.resolve(WEAPON)
    impact=(weapon.get('Behaviors') or [{}])[0].get('impact:LotusWeaponImpactBehavior') or {}
    if impact.get('DamageUpgradeTypes')!=['WEAPON_DAMAGE_AMOUNT']:
        raise ValueError('Mutalist Cernos source weapon upgrade context changed')
    callback=embed.get('ScriptInstance') or {};attack=trigger.get('AttackData') or {}
    if (projectile.get('EmbedEffect')!=EMBED or projectile.get('EmbedTime')!=[10,10]
        or (callback.get('Script'),callback.get('Function'),callback.get('_damageTriggerType'))!=(SCRIPT,'OnProjectileStopped',TRIGGER)
        or trigger.get('DamageOnEnter')!=1 or trigger.get('DamageOverTimeInterval')!=.5
        or trigger.get('DamageDuration')!=2 or trigger.get('DamageSource')!='PLAYER_AVATAR'
        or trigger.get('DamageAttachedParent')!=0
        or attack!={'Type':'DT_POISON','Amount':3,'ProcChance':1,'ForcedProcs':['PT_POISONED'],'HitType':'DHT_PROJECTILE'}):
        raise ValueError('Mutalist Cernos swarm trigger contract changed')
    return dict(name='Mutalist Cernos',fireMode=0,directTotal=410.,projectile=PROJECTILE,
        periodicTriggers=[dict(id='mutalist-cernos-swarm',damage={'toxin':3.},
            nativeSource=TRIGGER,nativeField='AttackData',sourceHitType='DHT_PROJECTILE',
            status_chance=1.,forcedProcs=['PT_POISONED'],crit_chance=0.,crit_multiplier=1.,
            interval_seconds=.5,tick_rate=2.,damageOnEnter=True,
            countPolicy='one-current-weapon-field-per-covered-target',
            admission='source-projectile-embed-with-centered-target-coverage',defaultEnabled=True,
            coverageModel='inherit-enclosing-centered-target-assumption',maxConcurrentFieldsPerSource=1,
            sourceModifierAllowlist=['weapon-base-damage','ordinary-weapon-elements'],
            firstPeriodicPhase='next-authoritative-update-if-constructor-clock-zero',
            clockPolicy='decrement-dt-single-dispatch-reset-interval-no-catch-up',
            activation_event='source-projectile-embed',first_periodic_delay_seconds=0.,
            firstPeriodicDelayModel='first-authoritative-update-collapsed-to-activation-time',
            duration_seconds=10.,expiryBoundary='owner-removal-before-further-field-damage',
            refreshPolicy='replace-entity-and-reset-timer-not-extend-existing-clock',
            damageOnEnterSeparateFromFirstPeriodic=True,
            lifetimePolicy='source-arrow-owner-expiry-or-replacement-no-DamageDuration-cutoff',
            sourceOwnerLifetimeAfterEmbed_seconds=10.,expiresWithSourceOwner=True,
            replacementPolicy='destroy-previous-live-weapon-projectile-before-registering-new-field',
            replacementKey='source-weapon-WeaponUtil.Projectile',
            damageSource='PLAYER_AVATAR',sourceUpgradeRouting='projectile-creator-weapon',
            damageUpgradeTypes=['WEAPON_DAMAGE_AMOUNT'],
            takes_weapon_base_damage=True,takes_weapon_elements=True,
            takes_parent_crit=False,takes_parent_status_chance=False,
            payloadMultishotMultiplier=False,
            multiplicityPolicy='not-inferred-from-weapon-fire-iterations',
            radius_m=2.5,activeAfter='OnProjectileStopped-spawn-callback')],
        scope='one current source-weapon swarm at target center; native 3 toxin per .5s independently from arrow EmbedAttack; source-arrow owner lifetime bounded by10seconds from embedding and truncated by replacement; exact activation/update/expiry frame phase excluded',
        unmodeled=list(UNMODELED),source=dict(packagesBinSha256=PACKAGE_SHA256,clientSha256=CLIENT_SHA256,
            script=SCRIPT,scriptSha256=SCRIPT_SHA256,
            spawn='InfCernos P0 pc85..98 creates _damageTriggerType at arrow position on host',
            sourceAssignment='P0 pc117..122 arrow+0x708 getter0x14197af60 -> Entity wrapper0x141972340 -> native0x140570710 -> trigger+0x400',
            sourceConsumer='0x140e5fd6b reads trigger+0x400; 0x140e5fdd6 resolves packet source; 0x140e5fde3..0x140e5fe34 validates LotusWeapon',
            baseDamageConsumer='0x140e5ff7b weapon+0xaa0 upgrade list; 0x140e5ffbb ->0x1401413d0; actual route reproduces source multipliers1/2/3 as3/6/9',
            elementalConsumer='0x140e60081..0x140e600c5 ->0x1403a6ea0 ->0x14171a350 with0x166 WEAPON_PERCENT_BASE_DAMAGE_ADDED; numerical combinations not replayed here',
            forcedProcConsumer='0x140e5fe58 ->0x140451710 asks0x119 WEAPON_FORCED_PROC_CHANCE before converting trigger AttackData; no parent status chance read',
            periodicConsumer='vtable0x1421635e0 slot0x230 ->0x141319fd0 ->0x141463ae0; +0x6b0 interval, +0x6c0 remaining, +0x660 ->0x1410f1e50 ->0x140e5f490',
            clockInitial='constructor0x14024444c initializes +0x6c0 zero; update0x141463c24 subtracts dt, dispatches once if<=0 then resets .5 without catch-up',
            attachment='P0 pc105..110 -> Lua wrapper0x14196c880 -> actual DamageTrigger slot0x298=0x141662640; inserts trigger handle in arrow+0x3b0 and writes trigger+0x3a0 parent',
            parentInheritance='Entity constructor0x140529b6d..74 sets both dead/live parent rules2; this transfer rule is separate from native owner cleanup',
            ownerRegistration='P0 pc94..98 passes arrow as sixth CreateEntity argument;0x141a24181 ->0x1400ef550 writes CreateParams+0x10;0x140cb72b3..0x140cb72fd registers child handle in Entity service owner map+0x1f0',
            ownerCleanup='Entity service vtable0x1421a0a28 slot0x1f8=0x1402201a0 ->0x140185a50;0x140185c9b..0x140185cf5 recursively removes registered owner children then marks source+0x20 and queues removal; unchanged bytes reproduce child-before-owner deletion',
            ownerExpiry='mEmbedTime serializer0x140da1fc1 maps projectile+0x8ec..0x8f0;0x140c3f156..0x140c3f1a4 schedules0x1402e1be0 using EmbedTime10; callback eventually0x140f4f1a0 -> Entity service removal',
            replace='P0 pc37..83 WeaponUtil Projectile reference destroys previous source before storing new arrow',
            damageOnEnter='0x14132ac78..0x14132ac9d tests DamageOnEnter+0x6ce and calls 0x140e5f490',
            rawAttack='0x140e5fab4 loads trigger AttackData+0x610; 0x140e5fe68 calls original packet converter',
            duration='DamageDuration+0x6b4 is only read after positive start multiplier +0x6b8 at0x140e600ca; default start multiplier0 means no lifetime cutoff'))


def candidate_merge(reference,entry):
    result=deepcopy(reference);current=result['auditedAttacks'][WEAPON]
    if current.get('projectile')!=PROJECTILE or abs(float(current.get('directTotal',0))-410)>1e-4:
        raise ValueError('Mutalist Cernos current profile identity changed')
    current['periodicTriggers']=entry['periodicTriggers'];current['swarmSource']=entry['source']
    current['unmodeled']=list(dict.fromkeys([*(current.get('unmodeled') or []),*entry['unmodeled']]))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--packages-bin',type=Path,required=True);p.add_argument('--client-exe',type=Path,required=True)
    p.add_argument('--script-body',type=Path,required=True);p.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    p.add_argument('--evidence',type=Path,required=True)
    a=p.parse_args()
    if a.evidence.exists():p.error('preserve evidence; choose a new file')
    for f,sha in [(a.client_exe,CLIENT_SHA256),(a.script_body,SCRIPT_SHA256)]:
        if hashlib.sha256(f.read_bytes()).hexdigest()!=sha:raise ValueError('native/script source identity changed')
    packages=AuditedPackages(a.packages_bin)
    row=next(w for w in json.loads(a.export.read_bytes())['data'] if w['path']==WEAPON)
    a.evidence.parent.mkdir(parents=True,exist_ok=True);a.evidence.write_text(json.dumps(profile(packages,row),indent=2)+'\n',encoding='utf-8')
    print('Wrote source-owner bounded single-field profile for production centered-target scoring')

if __name__=='__main__':main()
