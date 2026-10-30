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
    if (p.get('Embed')!=1 or p.get('EmbedTime')!=[2,4]
            or p.get('AttackData',{}).get('Amount')!=30 or p.get('EmbedAttack',{}).get('Amount')!=3
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
    return dict(status='script-declaration-and-partial-consumer-no-added-damage',clientSha256=CLIENT_SHA256,
        packagesSha256=PACKAGE_SHA256,script=SCRIPT,scriptSha256=SCRIPT_SHA,nativeSources=source_rows(pkg,[WEAPON,PROJECTILE,TRIGGER]),
        displayIdentity=dict(path=WEAPON,localizeTag=w.get('LocalizeTag'),marketMode=w.get('MarketMode'),availability='not-established-from-MarketMode'),
        nonDamageTrigger=dict(path=TRIGGER,hasAttackData=False,behavior='OnOverlap obtains parent and requests parent death; not another damage field'),
        declaredPayloads=dict(contact=deepcopy(p['AttackData']),embeddedTick=deepcopy(p['EmbedAttack']),embeddedDeath=deepcopy(p['EmbedDeathAttack']),embedTimeRange=[2,4]),
        consumers=dict(radius='OnStop P0pc131..135 Lua atomf6e051dd ->0x141981f90 writesProjectile+63c using script1.5; subsequent visualScale setter is independent',
            overlap='OnOverlap P2pc0..11 atom557c9672 ->0x14196cbb0 readsEntity+3a0;atom9c6a9ac9 ->0x14196e520 callsparent+418 death',
            branch='OnStop first branch tests private class atom0xae46e6de, alive and slow tracking; resolved class identity not yet established'),
        unresolved=['same-victim-overlap-and-host-class-branch','embed-tick-and-early-death-versus-uniform-expiry','weapon-context-and-final-event-consumers','script-raw0-loop-backedge-not-independently-decoded'],
        interpretation='No mean3s explosion or independent3toxin field admitted; overlap may end the owner before its native expiry')


def merge(reference,evidence):
    result=deepcopy(reference);entry=result.setdefault('auditedAttacks',{}).setdefault(WEAPON,{})
    entry['noxScriptAudit']=deepcopy(evidence)
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
    print('Nox exact-path audit: no added damage; overlap and native expiry remain separate')


if __name__=='__main__':main()
