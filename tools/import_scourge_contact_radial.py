"""Scourge Prime accepted-contact55 with explicit throw/reload/rethrow policy."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from copy import deepcopy
from tools.import_scourge_contact_contract import build_contract,WEAPON,PROJECTILE
from tools.import_native_secondary_payloads import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,SPECS,profile,sha256
ROOT=Path(__file__).resolve().parents[1]
BOUNDS=['scourge-prime-throw-reload-rethrow-input-policy-idealized',
    'scourge-prime-accepted-contact-flight-geometry-idealized',
    'scourge-prime-stopped-embedded-script-payload-unmodeled',
    'scourge-prime-main55-CO-weakpoint-events-neutral-fallback-unverified',
    'scourge-prime-pickup-recall-shortcuts-and-animation-interruption-unmodeled',
    'scourge-prime-old-spear-deferred-die-and-embedded-damage-excluded']

def build_patch(pkg,row):
    # Reuse the strict independent contact/count/state admission gate.
    contact=build_contract(pkg,row)['pending'][0];w=pkg.resolve(WEAPON);state=w['Behaviors'][1]['state:LotusSpearGunStateBehavior']
    if state.get('reloadTime')!=2.2 or state.get('fireRate')!=60 or state.get('IsAlternateFire')!=1:
        raise ValueError('Scourge source cadence signature changed')
    spec=deepcopy(next(x for x in SPECS if x['family']=='scourge-prime'));spec.update(delay=0.,bounds=list(BOUNDS))
    entry=profile(pkg,row,spec);part=entry['radials'][0]
    part['emissionContract'].update(physicalThrowsPerFire=1,packetsPerPhysicalThrow=1,nativeIgnoreFireIterations=True,
        consumer='Bolto+5781409397f0 ordinary accepted avatar14093a12c..a66b ->one+7b8at14093a64d ->common+630normalExplosiveAttack55')
    part['approximation'].update(flightAndCollisionTiming='immediate at idealized accepted contact; no expiry or embed55 added',
        cadence='explicit repeated throw then ordinary reload then next charge; prefire MaxNumProjectiles evicts previous spear')
    part['activationEvidence']=contact['evidence']
    entry['nativeCharge']=entry.pop('charge',None)
    entry.update(generatedBy='tools/import_scourge_contact_radial.py',scope='one physical spear; single main55 at accepted contact; explicit throw-reload-rethrow policy',
        nativeSpearThrowCycle=dict(policy='throw-reload-rethrow',reloadAfterEveryShot=True,reloadBaseSeconds=2.2,
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
            limits=list(BOUNDS)))
    return dict(schemaVersion=1,kind='auditedAttacks-mode-merge',clientSha256=CLIENT_SHA256,packageSha256=PACKAGE_SHA256,
        weapons={WEAPON:{'1':entry}},pending=[],interpretation='Explicit throw-reload-rethrow single-target policy; prefire enforces one active spear. Not a claim that lifetime/embedded aura damage or arbitrary manual pickup is simulated.')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True);ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():ap.error('choose a new output')
    if sha256(a.client_exe)!=CLIENT_SHA256:raise ValueError('native EXE changed')
    row=next(r for r in json.loads(a.export.read_bytes())['data'] if r['path']==WEAPON);out=build_patch(AuditedPackages(a.packages_bin),row);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8');print('PASS Scourge Prime accepted-contact55 under explicit throw-reload-rethrow policy')
if __name__=='__main__':main()
