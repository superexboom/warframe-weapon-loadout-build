"""Hash-gated Larkspur/Prime contact-death parent radial patch; no production writes.

Assumes the existing single-target contact geometry: a selected projectile hits
the modelled victim. Launch lifetime is a separate alternative, never a delay
relative to that hit. Empty-space expiry recipients remain excluded.
"""
from __future__ import annotations
import argparse,json
from copy import deepcopy
from pathlib import Path
from tools.import_native_secondary_payloads import (AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,SPECS,profile as packet_profile,sha256)
ROOT=Path(__file__).resolve().parents[1]
LARKSPUR_SPECS=tuple(s for s in SPECS if s['family']=='larkspur')
BOUNDS=[
 'larkspur-contact-flight-and-scene-geometry-idealized',
 'larkspur-maxlife1-launch-expiry-recipient-excluded-from-contact-model',
 'larkspur-projectile-speed-mods-obstacles-and-out-of-range-contact-unmodeled',
 'larkspur-flight-time-dynamic-buff-snapshot-unverified',
 'larkspur-main-explosion-CO-neutral-fallback-unverified',
 'larkspur-main-explosion-weakpoint-and-hit-events-neutral-fallback-unverified',
]
PROOF=dict(
 waveVtable='0x1423ebeb0',
 normalContact='serializer14013dcaa -> Wave+1822 AllowNormalContactBehavior=1; Wave+5781401f16d0 can route normal contact',
 acceptedCollision='0x1414447ee -> 0x14077fbb0; ordinary living avatar 140780e28..140780f33 sees ExplodeOnImpact0, cannot pierce positive-radius contact, calls projectile+568 -> 14037e980 -> +5601405ac4a0',
 deathOnce='0x1405ac4da checks c1d; first call stores c1d1 at1405ac65c; duplicate exits before property callback; c10 change at1405ac8ee calls native delegate1420af3d0+20 ->14012b2c0 ->140907fec -> projectile+768140163a60',
 selectedDeathPayload='0x140163b01..b34 with ExplodeOnImpact0/ExplodeOnLifeExpired0 calls +7b8 once; c250 -> common selector14160c689..6b2 selects ExplosiveAttack+5b4, never EmbedDeathAttack',
 launchLifetime='Wave actual virtual+780140f874b0 suffix140f88871..88981 calls140dd80d0 MaxLife+variance; ExplodeOnLifeExpired0 selects plain Projectile::Die thunk140273d98 after1s from launch, not DieOfOldAge; impact-first then scheduled Die is rejected by c1d',
 sourceUpgrade='base ctor140fbadf9 installs enum253 WEAPON_DAMAGE_AMOUNT in Projectile+db0; serializer140da0a9f and common builder141234bbb..c2e consume array; source chain has no override',
 amountScale='0x141234a75 ->14116ac70 applies source stage then141234a7a multiplies projectile+7b8; native initial+7b8=1 at140fba8cb, weapon state DamageMultiplier1/nonclip; no hardcoded direct840-derived scalar',
 radius='0x14160c665..67c multiplies native radius9.6000004 by Projectile+8101; positive radius admitted',
 contactClock='impact_delay_seconds0 denotes immediate contact-death packet under shared single-target geometry; launch flight ignored explicitly; MaxLife1 is not added after hit',
 onceScope='one radial per selected projectile that reaches ordinary victim contact; no extra life-expiry packet after contact death',
 evidence='.local/delivery/ranged-implementation-20261029/native-payloads/larkspur-lifecycle-original-byte-results.json')

def make_profile(pkg,row,spec):
    p=pkg.resolve(spec['projectile']);w=pkg.resolve(spec['path'])
    for field in ['ExplodeOnImpact','ExplodeOnLifeExpired','Embed']:
        if p.get(field,0)!=0:raise ValueError('Larkspur contact/death alternative changed: '+field)
    if p.get('MaxLifeVariance',0)!=0 or p.get('BounceOnAvatars')!=0:
        raise ValueError('Larkspur lifetime/bounce changed')
    if 'DamageUpgradeTypes' in p:raise ValueError('Larkspur source upgrade override changed')
    if pkg.parent(spec['projectile']) not in (
            '/Lotus/Weapons/Tenno/Archwing/Primary/TnShieldframeArchGun/TnShieldFrameArchgunProjectile',
            '/Lotus/Weapons/Tenno/Archwing/Primary/PrimeLarkspur/PrimeLarkspurProjectile'):
        raise ValueError('Larkspur Wave ancestry changed')
    bank=row.get('fireModeSource') or ('HeavyBehaviors' if w.get('HeavyBehaviors') else 'Behaviors')
    mode=w[bank][row['fireModes'][1].get('index',1)]
    fire=next(v for k,v in mode.items() if k.startswith('fire:') and isinstance(v,dict))
    state=next(v for k,v in mode.items() if k.startswith('state:') and isinstance(v,dict))
    if (fire.get('playerDamageMultiplier')!=1 or fire.get('AttenuateForCharge')!=0
            or fire.get('AttenuateFireIterationsForCharge')!=0
            or state.get('UseClipSizeAsDamageMultiplier')!=0 or state.get('DamageMultiplier')!=1):
        raise ValueError('Larkspur charged source scale changed')
    spec=deepcopy(spec);spec.update(delay=0.,bounds=list(BOUNDS))
    entry=packet_profile(pkg,row,spec);part=entry['radials'][0]
    part['emissionContract']['consumer']='contact+568 -> Die+560 -> property delegate -> death+768 -> radial+7b8 -> common+630/+638'
    part['activationEvidence']=deepcopy(PROOF)
    part['approximation']['flightAndCollisionTiming']='contact-death immediate at existing idealized hit time; launch lifetime excluded'
    part['approximation']['recipient']='victim at accepted contact/explosion centre assumed; empty-space expiry excluded'
    part['sourceDamageUpgrade']='WEAPON_DAMAGE_AMOUNT native constructor253'
    entry['nativeCharge']=entry.pop('charge',None)
    entry['scope']='ordinary single-target contact-death1600 radial once per projectile; launch-expiry alternatives excluded'
    entry['nativeEvidence']['lifecycle']=deepcopy(PROOF)
    entry['nativeEvidence']['critFields']='Projectile+538/+570 CriticalChance/CriticalMultiplier; radial callback140f36187..36198 calls140ede780 after selector to copy+combine crit state; plan118/11c are not crit proof'
    entry['generatedBy']='tools/import_larkspur_contact_radial.py'
    return entry

def build_patch(pkg,rows):
    by={r['path']:r for r in rows};weapons={}
    for spec in LARKSPUR_SPECS:weapons[spec['path']]={'1':make_profile(pkg,by[spec['path']],spec)}
    return dict(schemaVersion=1,kind='auditedAttacks-mode-merge',clientSha256=CLIENT_SHA256,packageSha256=PACKAGE_SHA256,
        weapons=weapons,pending=[],interpretation='contact-conditioned parent radial; never add fixed post-impact1s lifetime or an extra expiry packet')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True)
    ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():ap.error('choose a new evidence output')
    if sha256(a.client_exe)!=CLIENT_SHA256:raise ValueError('native EXE changed')
    patch=build_patch(AuditedPackages(a.packages_bin),json.loads(a.export.read_bytes())['data'])
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(patch,indent=2)+'\n',encoding='utf-8');print('PASS2 contact-death profiles; production untouched')
if __name__=='__main__':main()
