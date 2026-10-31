"""Scourge / Prime contact55 and source-owned attached50 under explicit rethrow policy."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from copy import deepcopy
from tools.import_scourge_contact_contract import build_contract,WEAPON,PROJECTILE,VARIANTS
from tools.import_native_secondary_payloads import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,SPECS,profile,sha256
ROOT=Path(__file__).resolve().parents[1]
BOUNDS=['scourge-prime-throw-reload-rethrow-input-policy-idealized',
    'scourge-prime-accepted-contact-flight-geometry-idealized',
    'scourge-prime-contact-main55-body-geometry-policy',
    'scourge-prime-pickup-recall-shortcuts-and-animation-interruption-unmodeled',
    'scourge-prime-original-surviving-host-attachment-policy']

def build_patch(pkg,row):
    # Reuse the strict independent contact/count/state admission gate.
    variant=VARIANTS[row['path']];weapon=row['path'];projectile_path=variant['projectile']
    bounds=[note.replace('scourge-prime',variant['family']) for note in BOUNDS]
    contact=build_contract(pkg,row)['pending'][0];w=pkg.resolve(weapon);projectile=pkg.resolve(projectile_path);state=w['Behaviors'][1]['state:LotusSpearGunStateBehavior']
    if state.get('reloadTime')!=variant['reload'] or state.get('fireRate')!=60 or state.get('IsAlternateFire')!=1:
        raise ValueError('Scourge source cadence signature changed')
    embed=projectile.get('EmbedAttack') or {}
    if (embed.get('Amount')!=50 or embed.get('Type')!='DT_PHYSICAL'
            or abs(embed.get('DT_IMPACT',0)-.7)>2e-8 or embed.get('DT_PUNCTURE')!=.1
            or abs(embed.get('DT_SLASH',0)-.2)>2e-8 or embed.get('ProcChance')!=.050000001
            or projectile.get('EmbedDamageRadius',0)!=0 or projectile.get('EmbedTime')!=[10,10]
            or state.get('DoPreFire')!=1 or state.get('PrefireTime')!=0 or state.get('FireOnButtonAction')!='PRESSED'):
        raise ValueError('Scourge attached50 source/period/replacement contract changed')
    spec=deepcopy(next(x for x in SPECS if x['family']=='scourge-prime'));spec.update(path=weapon,projectile=projectile_path,direct=variant['direct'],delay=0.,bounds=bounds)
    entry=profile(pkg,row,spec);part=entry['radials'][0]
    part['emissionContract'].update(physicalThrowsPerFire=1,packetsPerPhysicalThrow=1,nativeIgnoreFireIterations=True,
        consumer='Bolto+5781409397f0 ordinary accepted avatar14093a12c..a66b ->one+7b8at14093a64d ->common+630normalExplosiveAttack55')
    part['approximation'].update(flightAndCollisionTiming='immediate at idealized accepted contact; no expiry or embed55 added',
        cadence='explicit repeated throw/refire/reload then next trigger; prefire cancels previous spear embed delegate')
    part['activationEvidence']=contact['evidence']
    entry['nativeCharge']=entry.pop('charge',None)
    entry.update(generatedBy='tools/import_scourge_contact_radial.py',scope='one physical spear; contact55 followed by native attached50 every1s on original surviving host; explicit throw-reload-rethrow policy',
        attachedTicks=dict(damage={'DT_IMPACT':35.,'DT_PUNCTURE':5.,'DT_SLASH':10.},
            status_chance=.050000001,crit_chance=variant['crit'],crit_multiplier=2.,takes_multishot=False,
            tick_rate=1.,duration_seconds=10.,nativeSource=projectile_path,nativeField='EmbedAttack',
            nativeRoute='zero-radius-embed',native_event_delay_seconds=0.,
            takes_victim_crit=False,takes_condition_overload=False,sourceDestroyOnNextFire=True,
            sourceHitType='DHT_DOT',excludesTypedFlat=True,forcedProcs=[],
            genericHitEvent=True,genericCritEvent=True,headshotEligible=False,
            sourceCritPolicy='retained-launch-crit',sourceQueryPolicy='current-damage-and-status',
            recipientPolicy='original-surviving-physically-attached-victim',
            packetOrder=f"contact{variant['direct']:g}-main55-immediate50-then-1s",
            provenance='source-context/scourge/NOTES.md; EXE/Packages SHA pinned by nativeEvidence'),
        nativeSpearThrowCycle=dict(policy='throw-reload-rethrow',reloadAfterEveryShot=True,reloadBaseSeconds=variant['reload'],
            refireBaseSeconds=1.,firstShot='existing-initially-ready-selected-mode',activeProjectileLimit=1,oldSpearRemoval='automatic-prefire-destruction-request',oldSpearLifetimeWaitRequired=False,
            completion='existing idealized ordinary reload duration; accepts next explicit trigger',
            alternativePoliciesExcluded=['keep-spear-embedded-and-use-secondary','pickup-shortcut','manual-recall-shortcut']),
        nativeEvidence=dict({**entry['nativeEvidence'],**contact['evidence']},
            prefire='actual SpearState+d0141498140 calls selected+318140fbc360 when r8b1, then continues141330f10',
            maxEnforcement='140fbc428..445 counts local+58/8 plus replica+1b8/8 against+68; when occupied,140fbc490..49e dispatchesold14124eac0 ->+418;140fbc4aa..4b0 updates tracking. Actual Bolto418140414330 checks embedded8e1, not ScriptsPreventDestruction1589. Nonembedded8e10/15891 executes direct+560 Die; embedded8e11 with active script1e0 uses1402e1be0->14050b8c0 to schedule plainDie140273d98/pendingc34. Both continue original prefire141330f10. The two-field control matrix executes both1589 values',
            destructionFieldBinding='ScriptsPreventDestruction:serializer140da2aec..140da2b09 bindsProjectile+1589; embedded marker+8e1 is a separate runtime state',
            removal='actual+300141050a70 indexesprojectilef88 and compares current handle target to callback projectile at141050add; mismatchjne141050af5 skipsnull+dec. Match calls140154520 and141050ae9 decrementsactive108. Original full suffix1415e7d70 appendsindex to118 removalqueue; local-slot reuse/duplicate safety verified, remote queue receiver ordering not emulated',
            hideRestore='SpearState+1f814026b2c0 dispatches140612180/140afd1d0; those readHideAttach+1a8, set/clearhidden1a4 and hide/showattachments',
            reload='hidden1a4 andReloadAfterEveryShot1a5 interceptstate1681402d4e10 ->state8; emitscontroller0x79 withweapon+2d0 reload duration. Normal reload completion remains existing animation-duration abstraction',
            contactQualification='main55 accepted explicit victim uses common+c24PROJECTILE2; common7b8 bypasses790/818CO, ordinary source no-ability victim suffix rejectsCO; genericHit/Crit yes; bodygeometry retained independently of victimcritmask',
            embedClock='Bolto+738140f25fa0 ->140c3ecb0 calls140297cf0 immediately then deduplicated1s delegate; radius0 builder140a58cb0 suppliesDOT7 and final retainedcrit140ede780; SC365 uses independent.05',
            embedSourceReplacement='next trigger prefire141498140 ->140fbc360 ->old+418140414330 ->1402e1be0 removesDoEmbedDamage140297cf0 via1417d6e70 immediately before deferredDie; independent inflicted statuses survive source removal',
            embedEvents='DOT7 skipsCO/weakpoint/victimcrit/flattyped265; actual victim340 authority1412dd461->141375771->1416a6207->14179b840 accepts genericOnHit/OnCrit on own nonzero/critical packet; no sourceSendEvents gate',
            embedScript='OnPriestSpearEmbed only pickup/source ownership; UpdateAttractor managesHEAD bullet attractors, no independent DamageInfo payload',
            limits=bounds))
    return dict(schemaVersion=1,kind='auditedAttacks-mode-merge',clientSha256=CLIENT_SHA256,packageSha256=PACKAGE_SHA256,
        weapons={weapon:{'1':entry}},pending=[],interpretation='Explicit throw-reload-rethrow single-target policy; prefire enforces one active spear. Native attached50 uses original surviving host and cancels on next trigger; arbitrary manual pickup and attractor targeting are outside the selected policy.')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True);ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():ap.error('choose a new output')
    if sha256(a.client_exe)!=CLIENT_SHA256:raise ValueError('native EXE changed')
    pkg=AuditedPackages(a.packages_bin);patches=[build_patch(pkg,row) for row in json.loads(a.export.read_bytes())['data'] if row['path'] in VARIANTS];out={**patches[0],'weapons':{p:m for patch in patches for p,m in patch['weapons'].items()}};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8');print('PASS Scourge / Prime accepted-contact55 under explicit throw-reload-rethrow policy')
if __name__=='__main__':main()
