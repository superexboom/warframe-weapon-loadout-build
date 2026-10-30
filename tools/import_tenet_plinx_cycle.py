"""Import exact-build Tenet Plinx charge, payload and battery state contract.

Full-cycle scoring is excluded until attachment script timing and countdown reset
ordering is represented. The per-projectile arithmetic is independently complete.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from tools.import_native_secondary_payloads import AuditedPackages, CLIENT_SHA256, PACKAGE_SHA256, source_rows, sha256
ROOT = Path(__file__).resolve().parents[1]
DIR = '/Lotus/Weapons/Corpus/BoardExec/Secondary/CrpBEPlinx/'
WEAPON = DIR + 'CrpBEPlinxWeapon'
PROJECTILE = DIR + 'CrpBEPlinxAltFireProj'
ATTACHMENTS = [DIR + 'CrpBEPlinxAttachment', DIR + 'CrpBEPlinxDSAttachment']
LIMITS = ['tenet-plinx-attachment-tick-and-countdown-reset-order-unmodeled',
          'tenet-plinx-ideal-accepted-embed-contact-geometry',
          'tenet-plinx-CO-weakpoint-arcane-event-qualification-unverified',
          'tenet-plinx-flat-add-native-damage-provider-order-unverified']

def require(obj, fields, label):
    for key, value in fields.items():
        if obj.get(key) != value:
            raise ValueError(f'Tenet Plinx {label}.{key} changed: {obj.get(key)!r}')

def build_contract(pkg, row):
    if row.get('path') != WEAPON:
        raise ValueError('Tenet Plinx export identity changed')
    w, p = pkg.resolve(WEAPON), pkg.resolve(PROJECTILE)
    mode = w['Behaviors'][1]
    state = mode['state:WeaponChargedStateBehavior']
    fire = mode['fire:LotusWeaponProjectileFireBehavior']
    require(w, dict(AmmoClipSize=10, ClipIsBattery=1, BatteryRegenDelay=.80000001,
                   BatteryRegenRate=20, NotifyAttachmentState=1), 'weapon')
    require(state, dict(ChargeTime=.80000001, MinChargeRatio=1,
                       UseClipSizeAsDamageMultiplier=1, UseClipWhileCharging=1,
                       ChargeRequireFullClip=1, ClipSizeAffectsChargeTime=0,
                       MinDamageMultiplier=1, MaxDamageMultiplier=0), 'state')
    require(fire, dict(fireIterations=1, UseAmmo=0, AttenuateForCharge=0,
                      AttenuateFireIterationsForCharge=0, playerDamageMultiplier=1), 'fire')
    if pkg.locate(WEAPON, fire['chargedProjectileType']) != PROJECTILE:
        raise ValueError('Tenet Plinx charged projectile changed')
    require(p, dict(Embed=1, EmbedTime=[.80000001, .80000001], DamageRadius=6,
                    ExplosionFallOff=.40000001, CriticalChance=.40000001,
                    CriticalMultiplier=3), 'projectile')
    require(p['AttackData'], dict(DT_IMPACT=1, DT_PUNCTURE=0, DT_SLASH=0, Amount=100, ProcChance=.2), 'direct')
    require(p['EmbedDeathAttack'], dict(Type='DT_RADIATION', Amount=100, ProcChance=.5, ForcedProcs=['PT_RAGDOLL']), 'embedded')
    require(p['ExplosiveAttack'], dict(Type='DT_RADIATION', Amount=500, ProcChance=.2), 'unembedded')
    require(p['EmbedAttack'], dict(Amount=0), 'embed contact')
    events = []
    for path in ATTACHMENTS:
        matches = [e for e in pkg.resolve(path)['OnEnter'] if
                   e.get('responseScript', {}).get('Function') in
                   ('ChangeRegenDelayToNormal', 'ChangeRegenDelayToAltFire')]
        if len(matches) != 2:
            raise ValueError('Tenet Plinx attachment scripts changed')
        for e in matches:
            normal = e['responseScript']['Function'] == 'ChangeRegenDelayToNormal'
            require(e, dict(state='WS_FIRE', matchTransitionState=0,
                            activeBehaviorIndexIgnoreList=[1 if normal else 0]), 'event')
            events.append(dict(attachment=path, function=e['responseScript']['Function'],
                               activeMode=0 if normal else 1, state='WS_FIRE'))
    charge = dict(policy='full-clip-damage-scale', seconds=.80000001,
                  chargeRateModifier='WEAPON_FIRE_RATE', requiresFullClip=True,
                  consumesLoadedCapacity=True, consumptionPhase='charge-progress',
                  usesNormalFireAmmo=False, rawProjectiles=1,
                  damageScale='ammoAtChargeStart', clipSizeScalesDuration=False)
    payload = dict(direct=dict(damage={'impact':100.}, statusChance=.2),
                   embeddedDeath=dict(damage={'radiation':100.}, statusChance=.5,
                                      delayAfterAcceptedEmbed=.80000001),
                   unembeddedDeathAlternative=dict(damage={'radiation':500.}, statusChance=.2),
                   deathPacketSelection='exclusive-embedded-flag', critChance=.40000001,
                   critMultiplier=3., radius_m=6., falloff=.40000001,
                   scaleAllPackets='ammoAtChargeStart', ordinaryMultishot='physical-projectiles',
                   nativeModifierOrder=['source-provider14116ac70','N','140b42420'],
                   flatAddOrderVerified=False)
    battery = dict(capacity=10, regenPerSecond=20., partialDelaySeconds=.80000001,
                   normalConfiguredEmptyDelay=1., altConfiguredEmptyDelay=3.,
                   luaAltOrder=['setAmmo0','setConfiguredEmptyDelay3'],
                   reloadDelayFormula='(emptyDelay*query0x184 + query0x186)/max(query0x185,0.01)',
                   regenRateQuery='0xe2', configuredDelaySetterResetsCountdown=False,
                   stateResetBeforeAttachmentNotification=True,
                   activeCountdownMustBeSeparateState=True, attachmentEvents=events)
    operational = dict(directTotal=100., projectile=PROJECTILE,
        charge=dict(seconds=.80000001,beforeFire=True,scalesWithFireRate=True),
        fullClipCharge=dict(cadencePolicy='wait-configured-empty-delay-then-full-recharge',
            chargeSeconds=.80000001,emptyDelaySeconds=3.,regenPerSecond=20.,capacityPolicy='static-modified-capacity'),
        battery=dict(delayEmptySeconds=3.,delayPartialSeconds=.80000001,regenPerSecond=20.),
        radial=dict(damage={'radiation':100.},crit_chance=.40000001,crit_multiplier=3.,
            status_chance=.5,radius_m=6.,falloff_reduction=.40000001,forcedProcs=['PT_RAGDOLL'],impact_delay_seconds=.80000001,
            takes_condition_overload=False),
        unmodeled=['tenet-plinx-static-magazine-policy-charge-entry-capacity-snapshot-unmodeled',
                   'tenet-plinx-cadence-player-wait-policy-not-native-max-rate',
                   'tenet-plinx-flat-add-native-damage-provider-order-fail-closed',
                   'tenet-plinx-ideal-accepted-embed-contact-geometry',
                   'tenet-plinx-unembedded500-alternative-excluded',
                   'tenet-plinx-CO-weakpoint-arcane-event-qualification-unverified'])
    return dict(schemaVersion=1, kind='native-tenet-plinx-cycle-contract', weapons={},
                operationalPatch=dict(weapons={WEAPON:dict(modes={'1':operational})}),
                pending=[dict(path=WEAPON, mode=1, candidateOnly=True, defaultScoringExcluded=True,
                    sourcePayload=dict(charge=charge, payload=payload, battery=battery),
                    unmodeled=list(LIMITS))],
                enginePatchContract=dict(charge=charge, payload=payload, battery=battery,
                    reuseBattery=True, reuseChargeVolley=False,
                    required=['capture-full-clip-on-charge-entry','scale-damage-not-pellet-count',
                              'exclusive-death-packet','embed-relative-timer',
                              'script-configured-delay-separate-from-active-countdown']),
                evidence=dict(clientSha256=CLIENT_SHA256, packageSha256=PACKAGE_SHA256,
                    nativeSources=source_rows(pkg,[WEAPON,PROJECTILE,*ATTACHMENTS]),
                    nativeCharge='140b7eae0;1405774f0;1418abeb0;1405cb0b1;1403c4a1d',
                    nativeFullClipGate='1403ceb41..1403cebdb',
                    nativeBattery='141b0f270;140f07250;1402bb5f3..1402bb734',
                    nativeStateOrder='140f67bc6 store;140f67bcd owner+c18;140f6823c owner+bd8',
                    nativeAttachment='14073f0f0 -> attachment+5c8, +568;141610c40 attachment transition update; vector classification pending',
                    validation='original-byte arithmetic with explicit owner/VM/property stubs; no live-game validation'))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages-bin',type=Path,required=True)
    ap.add_argument('--client-exe',type=Path,required=True)
    ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists(): ap.error('choose a new evidence output')
    if sha256(a.client_exe)!=CLIENT_SHA256: raise ValueError('native client changed')
    row=next(r for r in json.loads(a.export.read_bytes())['data'] if r['path']==WEAPON)
    out=build_contract(AuditedPackages(a.packages_bin),row)
    a.output.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print('PASS Tenet Plinx charge/payload/battery source; full-cycle scheduling remains explicit')
if __name__=='__main__': main()
